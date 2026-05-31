#!/usr/bin/env python3
"""
Valida a acurácia do prompt de get_llm_conversion_suggestions contra dados reais do banco.

Usa fatores de conversão já validados de um schema NoHarm como ground truth,
amostrando aleatoriamente N medicamentos com seed reproduzível.

Uso:
    env/bin/python3 scripts/validate_unit_conversion_inference.py \\
        --schema meu_schema --samples 30 --seed 42

    # dry-run: só mostra os prompts sem chamar Bedrock
    env/bin/python3 scripts/validate_unit_conversion_inference.py \\
        --schema meu_schema --samples 10 --seed 42 --dry-run
"""
import argparse
import json
import os
import random
import re
import sys
from dataclasses import dataclass
from itertools import groupby

try:
    import boto3
    import psycopg2
except ImportError as e:
    sys.exit(f"Dependência ausente: {e}. Execute: pip install boto3 psycopg2-binary")

# Add project root to path so we can import from services
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from services.admin.admin_unit_conversion_service import build_conversion_messages


# ── .env loader (sem dependência externa) ─────────────────────────────────────

def _load_dotenv(path: str = ".env") -> None:
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())
    except FileNotFoundError:
        pass


_load_dotenv()

# ── Bedrock ───────────────────────────────────────────────────────────────────

MODEL_ID = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
REGION = "us-east-1"
MAX_TOKENS = 1024

# Aliases para facilitar --model na linha de comando
MODEL_ALIASES: dict[str, str] = {
    "haiku":       "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    "haiku45":     "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    "sonnet":      "global.anthropic.claude-sonnet-4-6",
    "opus":        "global.anthropic.claude-opus-4-8",
    "qwen3next":   "qwen.qwen3-next-80b-a3b",
    "deepseekv32": "deepseek.v3.2",
    "kimik25":     "moonshotai.kimi-k2.5",
    "minimax21":   "minimax.minimax-m2.1",
    "minimax25":   "minimax.minimax-m2.5",
    "gptoss120b":  "openai.gpt-oss-120b-1:0",
}

# Fallback pricing table for models not yet in the AWS Pricing API (USD per 1M tokens)
# Preços do perfil global sa-east-1 (São Paulo)
_FALLBACK_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude haiku 4.5":     ( 1.00,  5.00),
    "claude sonnet 4":      ( 3.00, 15.00),
    "claude sonnet 4.5":    ( 3.00, 15.00),
    "claude sonnet 4.6":    ( 3.00, 15.00),
    "claude opus 4.5":      ( 5.00, 25.00),
    "claude opus 4.6":      ( 5.00, 25.00),
    "claude opus 4.7":      ( 5.00, 25.00),
    "claude opus 4.8":      ( 5.00, 25.00),
    # Outros providers
    "deepseek v3.2":          (0.62, 1.85),
    "gpt-oss-20b":            (0.07, 0.30),
    "gpt-oss-120b":           (0.15, 0.60),
    "qwen3 coder 30b a3b":    (0.18, 0.73),
    "qwen3-coder-30b-a3b-instruct": (0.18, 0.73),
    "qwen3 32b (dense)":      (0.18, 0.73),
    "qwen3 next 80b a3b":     (0.15, 1.20),
    "qwen3 coder next":       (0.50, 1.20),
    "qwen3 vl 235b a22b":     (0.53, 2.66),
    # MiniMax
    "minimax m2":             (0.30, 1.20),
    "minimax m2.1":           (0.30, 1.20),
    "minimax m2.5":           (0.30, 1.20),
    # Kimi
    "kimi k2.5":              (0.60, 3.00),
    "kimi k2 thinking":       (0.60, 2.50),
}


def _normalize_model_name(name: str) -> str:
    return name.lower().strip()


def _fetch_pricing_from_api() -> dict[str, tuple[float, float]]:
    """Query AWS Pricing API for Bedrock Anthropic models. Returns {model_name: (input, output)} per 1M tokens."""
    pricing: dict[str, tuple[float, float]] = {}
    try:
        client = boto3.client('pricing', region_name='us-east-1')
        paginator = client.get_paginator('get_products')
        pages = paginator.paginate(
            ServiceCode='AmazonBedrock',
            Filters=[{'Type': 'TERM_MATCH', 'Field': 'provider', 'Value': 'Anthropic'}],
        )
        for page in pages:
            for raw in page['PriceList']:
                item = json.loads(raw)
                attrs = item['product']['attributes']
                model = _normalize_model_name(attrs.get('model', ''))
                inference_type = attrs.get('inferenceType', '').lower()
                for term in item['terms']['OnDemand'].values():
                    for dim in term['priceDimensions'].values():
                        price_per_1k = float(dim['pricePerUnit'].get('USD', 0))
                        price_per_1m = price_per_1k * 1000
                        inp, out = pricing.get(model, (0.0, 0.0))
                        if 'input' in inference_type:
                            pricing[model] = (price_per_1m, out)
                        elif 'output' in inference_type:
                            pricing[model] = (inp, price_per_1m)
    except Exception:
        pass
    return pricing


def get_model_pricing(model_id: str) -> tuple[float, float, str]:
    """Return (input_per_1M, output_per_1M, source) for a Bedrock model ID."""
    # Resolve human-readable name via Bedrock API (try full ID, then base ID)
    model_name = ""
    bedrock = boto3.client('bedrock', region_name=REGION)
    for candidate in [model_id, model_id.split('.')[-1]]:
        try:
            resp = bedrock.get_foundation_model(modelIdentifier=candidate)
            model_name = _normalize_model_name(resp['modelDetails'].get('modelName', ''))
            if model_name:
                break
        except Exception:
            pass

    # Try AWS Pricing API first
    api_pricing = _fetch_pricing_from_api()
    if model_name and model_name in api_pricing:
        inp, out = api_pricing[model_name]
        if inp > 0 or out > 0:
            return inp, out, "AWS Pricing API"

    # Fall back to local table (exact match)
    if model_name and model_name in _FALLBACK_PRICING:
        return *_FALLBACK_PRICING[model_name], "tabela local"

    # Partial match only when we have a real model name
    if model_name:
        for key, prices in _FALLBACK_PRICING.items():
            if key in model_name or model_name in key:
                return *prices, f"tabela local (match parcial: {key})"

    return 0.0, 0.0, "não encontrado"

# ── DB ────────────────────────────────────────────────────────────────────────

def _db_config() -> dict:
    missing = [k for k in ("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME") if not os.getenv(k)]
    if missing:
        sys.exit(f"Variáveis de ambiente ausentes: {', '.join(missing)}\nDefina-as no .env ou no ambiente.")
    return {
        "host": os.environ["DB_HOST"],
        "port": int(os.getenv("DB_PORT", "5432")),
        "dbname": os.environ["DB_NAME"],
        "user": os.environ["DB_USER"],
        "password": os.environ["DB_PASSWORD"],
    }

TOLERANCE_PCT = 5.0


# ── tipos ─────────────────────────────────────────────────────────────────────

@dataclass
class TestCase:
    drug_id: int
    drug_name: str
    substance_name: str
    sctid: int | None
    unidade_noharm: str
    fkunidademedida: str
    expected_factor: float
    substance_ref: str


@dataclass
class CaseResult:
    case: TestCase
    predicted: float | None
    passed: bool
    error: str | None = None

    def status(self) -> str:
        if self.error:
            return "ERRO"
        if self.predicted is None:
            return "NULL"
        return "OK" if self.passed else "FALHOU"


# ── DB helpers ────────────────────────────────────────────────────────────────

def _strip_html(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_atributos(html: str) -> str:
    text = _strip_html(html)
    m = re.search(
        r"Atributos[:\s]*(.*?)(?:Classe Terapêutica|Indicação|Posologia|$)",
        text, re.DOTALL | re.IGNORECASE,
    )
    return m.group(1).strip()[:300] if m else ""


def load_cases_from_db(schema: str, n_samples: int, seed: int) -> list[TestCase]:
    conn = psycopg2.connect(**_db_config())
    cur = conn.cursor()

    query = f"""
        SELECT DISTINCT ON (m.fkmedicamento, uc.fkunidademedida)
            m.fkmedicamento,
            m.nome                                        AS drug_name,
            s.sctid,
            s.nome                                        AS substance_name,
            COALESCE(s.unidadepadrao, 'unidade')          AS unidade_noharm,
            uc.fkunidademedida,
            uc.fator                                      AS factor,
            s.curadoria
        FROM {schema}.unidadeconverte uc
        JOIN {schema}.medicamento m ON m.fkmedicamento = uc.fkmedicamento
        JOIN public.substancia s ON s.sctid = m.sctid
        WHERE uc.fator IS NOT NULL
          AND uc.fator != 0
          AND m.nome IS NOT NULL
          AND m.sctid IS NOT NULL
        ORDER BY m.fkmedicamento, uc.fkunidademedida, uc.idsegmento
    """

    cur.execute(query)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    all_cases = [
        TestCase(
            drug_id=r[0],
            drug_name=r[1],
            sctid=r[2],
            substance_name=r[3] or "",
            unidade_noharm=r[4],
            fkunidademedida=r[5],
            expected_factor=float(r[6]),
            substance_ref=_extract_atributos(r[7]) if r[7] else "",
        )
        for r in rows
        if r[1] and r[5]
    ]

    rng = random.Random(seed)
    # amostragem por medicamento: garante diversidade de drogas, não apenas de unidades
    drugs = {}
    for c in all_cases:
        drugs.setdefault(c.drug_id, []).append(c)

    drug_ids = list(drugs.keys())
    rng.shuffle(drug_ids)

    sampled: list[TestCase] = []
    for did in drug_ids:
        sampled.extend(drugs[did])
        if len(sampled) >= n_samples:
            break

    return sampled[:n_samples]


# ── prompt ────────────────────────────────────────────────────────────────────
# Prompt construction is imported from the service to keep a single source of truth.
# build_conversion_messages(drug_name, substance_name, default_unit, units, clinical_notes)


def build_legacy_messages(
    drug_name: str,
    substance_name: str,
    default_unit: str,
    units: list[dict],
    clinical_notes: str = "",
) -> tuple[list, str]:
    """Original prompt before few-shot + CoT refactor — kept for A/B comparison."""
    units_json = json.dumps(units, ensure_ascii=False)
    substance_ref = "\n".join(filter(None, [
        f"Substance reference: {substance_name}",
        f"Standard substance unit: {default_unit}",
        clinical_notes,
    ]))

    user_message = (
        f"Drug: {drug_name}\n"
        f"Default unit (base): {default_unit}\n"
        f"{substance_ref}\n"
        f"\nFor each unit below, return the numeric conversion factor: "
        f"how many [{default_unit}] equal 1 unit of the given measure. "
        f"If you cannot determine a factor, use null.\n\n"
        f"Units to convert:\n{units_json}\n\n"
        f'Return format: [{{"idMeasureUnit": "ml", "factor": 1.0}}, ...]'
    )

    system = (
        "You are a clinical pharmacist expert in pharmaceutical units of measure. "
        "Your task is to determine conversion factors between medication units. "
        "Respond ONLY with a valid JSON array — no explanation, no markdown."
    )

    return [{"role": "user", "content": user_message}], system


# ── Bedrock ───────────────────────────────────────────────────────────────────

def call_bedrock(messages: list, system: str) -> tuple[list, int, int]:
    """Calls Bedrock Converse API (works for all providers). Returns (parsed_result, input_tokens, output_tokens)."""
    client = boto3.client("bedrock-runtime", region_name=REGION)

    converse_messages = [
        {"role": m["role"], "content": [{"text": m["content"]}]}
        for m in messages
    ]

    response = client.converse(
        modelId=MODEL_ID,
        system=[{"text": system}],
        messages=converse_messages,
        inferenceConfig={"maxTokens": MAX_TOKENS},
    )

    usage = response.get("usage", {})
    input_tokens = usage.get("inputTokens", 0)
    output_tokens = usage.get("outputTokens", 0)

    # Some models (MiniMax, reasoning models) prepend reasoningContent — find first text block
    text_block = next(
        (block["text"] for block in response["output"]["message"]["content"] if "text" in block),
        None,
    )
    if text_block is None:
        raise ValueError("No text content in model response")
    raw = text_block.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return json.loads(raw), input_tokens, output_tokens


# ── avaliação ─────────────────────────────────────────────────────────────────

def factors_match(predicted: float, expected: float) -> bool:
    if expected == 0:
        return predicted == 0
    return abs(predicted - expected) / abs(expected) * 100 <= TOLERANCE_PCT


def evaluate_group(cases: list[TestCase], dry_run: bool, old_prompt: bool = False) -> tuple[list[CaseResult], int, int]:
    """Returns (results, input_tokens, output_tokens)."""
    first = cases[0]
    units = [{"idMeasureUnit": c.fkunidademedida, "description": c.fkunidademedida} for c in cases]
    clinical_notes = f"Clinical notes: {first.substance_ref}" if first.substance_ref else ""
    builder = build_legacy_messages if old_prompt else build_conversion_messages
    messages, system = builder(
        drug_name=first.drug_name,
        substance_name=first.substance_name,
        default_unit=first.unidade_noharm,
        units=units,
        clinical_notes=clinical_notes,
    )

    if dry_run:
        print(f"\n{'─'*60}")
        print(f"[DRY-RUN] {first.drug_name[:70]}")
        print(messages[0]["content"])
        return [CaseResult(case=c, predicted=None, passed=False, error="dry-run") for c in cases], 0, 0

    try:
        llm_result, input_tok, output_tok = call_bedrock(messages, system)
    except Exception as e:
        print(f"  ERRO: {e}")
        return [CaseResult(case=c, predicted=None, passed=False, error=str(e)) for c in cases], 0, 0

    by_unit = {item["idMeasureUnit"]: item.get("factor") for item in llm_result}

    results = []
    for c in cases:
        raw_val = by_unit.get(c.fkunidademedida)
        if raw_val is None:
            results.append(CaseResult(case=c, predicted=None, passed=False))
            continue
        try:
            predicted = float(raw_val)
        except (TypeError, ValueError):
            results.append(CaseResult(case=c, predicted=None, passed=False))
            continue
        results.append(CaseResult(case=c, predicted=predicted, passed=factors_match(predicted, c.expected_factor)))

    return results, input_tok, output_tok


# ── relatório ─────────────────────────────────────────────────────────────────

def save_failures(results: list[CaseResult], path: str, model_id: str) -> None:
    """Save FALHOU and NULL cases to a JSON file for prompt improvement analysis."""
    failures = [
        {
            "status": r.status(),
            "drug_id": r.case.drug_id,
            "drug_name": r.case.drug_name,
            "substance_name": r.case.substance_name,
            "unit": r.case.fkunidademedida,
            "base_unit": r.case.unidade_noharm,
            "expected_factor": r.case.expected_factor,
            "predicted_factor": r.predicted,
            "deviation_pct": (
                round(abs(r.predicted - r.case.expected_factor) / abs(r.case.expected_factor) * 100, 1)
                if r.predicted is not None and r.case.expected_factor != 0
                else None
            ),
            "substance_ref": r.case.substance_ref,
        }
        for r in results
        if not r.passed and not r.error
    ]
    output = {"model": model_id, "total_failures": len(failures), "failures": failures}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nFalhas salvas em: {path}  ({len(failures)} casos)")


def print_report(
    results: list[CaseResult],
    schema: str,
    seed: int,
    input_tokens: int = 0,
    output_tokens: int = 0,
    price_input: float = 0.0,
    price_output: float = 0.0,
    price_source: str = "",
) -> None:
    total = len(results)
    n_ok = sum(1 for r in results if r.passed)
    n_fail = sum(1 for r in results if not r.passed and r.predicted is not None and not r.error)
    n_null = sum(1 for r in results if r.predicted is None and not r.error)
    n_err = sum(1 for r in results if r.error and r.error != "dry-run")

    cost = (input_tokens / 1_000_000 * price_input) + (output_tokens / 1_000_000 * price_output)

    print(f"\n{'='*72}")
    print(f"VALIDAÇÃO — get_llm_conversion_suggestions  schema={schema}  seed={seed}")
    print(f"{'='*72}")
    print(f"{'Total':<32} {total}")
    print(f"{'Corretos (tol ' + str(TOLERANCE_PCT) + '%)':<32} {n_ok}  ({n_ok/total*100:.1f}%)")
    print(f"{'Errado':<32} {n_fail}  ({n_fail/total*100:.1f}%)")
    print(f"{'Null / unidade não retornada':<32} {n_null}  ({n_null/total*100:.1f}%)")
    print(f"{'Erro de API':<32} {n_err}")
    print(f"{'─'*72}")
    print(f"{'Tokens input':<32} {input_tokens:,}")
    print(f"{'Tokens output':<32} {output_tokens:,}")
    if price_input > 0:
        print(f"{'Preço input ($/1M)':<32} ${price_input:.2f}  [{price_source}]")
        print(f"{'Preço output ($/1M)':<32} ${price_output:.2f}  [{price_source}]")
        print(f"{'Custo (USD)':<32} ${cost:.4f}")
    print(f"{'─'*72}")

    col = "{:<8} {:<12} {:<12} {}"
    print(col.format("STATUS", "PREDITO", "ESPERADO", "Medicamento  [unidade→base]"))
    print(f"{'─'*72}")

    for r in sorted(results, key=lambda x: (x.status(), x.case.drug_name)):
        pred_str = f"{r.predicted:.4g}" if r.predicted is not None else "—"
        exp_str = f"{r.case.expected_factor:.4g}"
        drug_short = r.case.drug_name[:44] + ("…" if len(r.case.drug_name) > 44 else "")
        pair = f"{r.case.fkunidademedida}→{r.case.unidade_noharm}"
        flag = ""
        if not r.passed and r.predicted is not None and not r.error:
            delta = abs(r.predicted - r.case.expected_factor) / abs(r.case.expected_factor) * 100
            flag = f"  (desvio {delta:.1f}%)"
        print(col.format(r.status(), pred_str, exp_str, f"{drug_short}  [{pair}]{flag}"))

    print(f"{'='*72}\n")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Valida inferência LLM de conversão de unidades")
    parser.add_argument("--schema", default="meu_schema", help="Schema NoHarm a usar como ground truth")
    parser.add_argument("--samples", type=int, default=30, help="Número de amostras (medicamentos)")
    parser.add_argument("--seed", type=int, default=42, help="Seed para reprodutibilidade")
    parser.add_argument("--dry-run", action="store_true", help="Mostra prompts sem chamar Bedrock")
    parser.add_argument("--old-prompt", action="store_true", help="Usa o prompt original (sem few-shot/CoT) para comparação")
    parser.add_argument("--model", default=None, help=f"Model ID ou alias ({', '.join(MODEL_ALIASES)})")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--save-failures", metavar="FILE", default=None, help="Salva casos FALHOU e NULL em JSON para análise")
    args = parser.parse_args()

    global MODEL_ID
    if args.model:
        MODEL_ID = MODEL_ALIASES.get(args.model, args.model)

    price_input, price_output, price_source = get_model_pricing(MODEL_ID)
    print(f"Modelo: {MODEL_ID}")
    print(f"Preço: ${price_input:.2f}/1M input, ${price_output:.2f}/1M output  [{price_source}]\n")

    print(f"Carregando amostras do schema '{args.schema}' (seed={args.seed}, N={args.samples})...")
    cases = load_cases_from_db(args.schema, args.samples, args.seed)
    print(f"  {len(cases)} casos carregados")

    def group_key(c: TestCase):
        return (c.drug_id, c.drug_name, c.unidade_noharm)

    cases.sort(key=group_key)
    groups = [(k, list(g)) for k, g in groupby(cases, key=group_key)]
    print(f"  {len(groups)} medicamentos → {len(groups)} chamadas ao modelo\n")

    all_results: list[CaseResult] = []
    total_input_tokens = 0
    total_output_tokens = 0
    for i, (key, group_cases) in enumerate(groups, 1):
        drug_id, drug_name, unit = key
        print(f"[{i}/{len(groups)}] {drug_name[:65]}  ({unit})")
        results, in_tok, out_tok = evaluate_group(group_cases, dry_run=args.dry_run, old_prompt=args.old_prompt)
        all_results.extend(results)
        total_input_tokens += in_tok
        total_output_tokens += out_tok

        if args.verbose and not args.dry_run:
            for r in results:
                mark = "✓" if r.passed else "✗"
                pred = f"{r.predicted:.4g}" if r.predicted is not None else "null"
                print(f"  {mark} {r.case.fkunidademedida}: pred={pred}  esperado={r.case.expected_factor}")

    if not args.dry_run:
        print_report(all_results, args.schema, args.seed, total_input_tokens, total_output_tokens, price_input, price_output, price_source)
        if args.save_failures:
            save_failures(all_results, args.save_failures, MODEL_ID)

    n_ok = sum(1 for r in all_results if r.passed)
    return 0 if n_ok == len(all_results) else 1


if __name__ == "__main__":
    sys.exit(main())
