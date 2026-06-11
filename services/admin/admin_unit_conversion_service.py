import json
from datetime import datetime

import boto3
import requests
from markupsafe import escape as escape_html
from sqlalchemy import text

from config import Config
from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.enums import DefaultMeasureUnitEnum
from models.main import (
    DrugAttributes,
    User,
    db,
)
from models.requests.admin.admin_unit_conversion_request import (
    AdminUnitConversionLLMRequest,
)
from models.segment import Segment
from repository import substance_repository, unit_conversion_repository
from services import drug_service as main_drug_service
from services.admin import (
    admin_drug_service,
)
from utils import logger, status


@has_permission(Permission.ADMIN_UNIT_CONVERSION)
def get_conversion_predictions(conversion_list: list) -> list:
    to_infer = []
    for index, conversion_item in enumerate(conversion_list):
        destiny_unit = conversion_item.get(
            "substanceMeasureUnit", DefaultMeasureUnitEnum.UN.value
        )

        if conversion_item.get("prediction", None) is None:
            # Sanitize user input to prevent XSS
            name = conversion_item.get("name")
            sctid = conversion_item.get("sctid")

            to_infer.append(
                {
                    "id": index,
                    "nome": escape_html(str(name)) if name is not None else None,
                    "unidade_noharm": destiny_unit,
                    "fkunidademedida": conversion_item.get("idMeasureUnit"),
                    "sctid": escape_html(str(sctid)) if sctid is not None else None,
                }
            )

    if to_infer:
        if not Config.SERVICE_INFERENCE:
            raise ValueError("SERVICE_INFERENCE not set")

        try:
            response = requests.post(
                f"{Config.SERVICE_INFERENCE}conversion-units/infer",
                json={"conversion_unit_list": to_infer},
                timeout=25,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException:
            raise ValidationError(
                "Serviço de inferência indisponível",
                "errors.serviceUnavailable",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        response_object = response.json()

        for item in response_object:
            try:
                if item.get("probability", 0) < 80:
                    conversion_list[item.get("id")]["prediction"] = "Curadoria"
                else:
                    conversion_list[item.get("id")]["prediction"] = float(
                        item.get("prediction")
                    )
            except ValueError:
                conversion_list[item.get("id")]["prediction"] = "Curadoria"

            conversion_list[item.get("id")]["probability"] = item.get("probability")

    return conversion_list


@has_permission(Permission.ADMIN_UNIT_CONVERSION)
def get_conversion_list():
    unit_conversion_repository.ensure_default_measure_units()

    nh_default_units = [
        DefaultMeasureUnitEnum.MCG.value,
        DefaultMeasureUnitEnum.MG.value,
        DefaultMeasureUnitEnum.ML.value,
        DefaultMeasureUnitEnum.UI.value,
        DefaultMeasureUnitEnum.UN.value,
    ]

    default_units = {}
    for du in nh_default_units:
        default_units[du] = {
            "idMeasureUnit": du,
            "description": du,
            "measureunit_nh": du,
        }

    conversion_list = unit_conversion_repository.get_unit_conversion_list()

    result = []
    drug_defaultunit = set()
    for i in conversion_list:
        prediction = None
        probability = None

        show_factors = True

        if not i.uniform_measure_unit:
            show_factors = False

        effective_default = i.default_measureunit or DefaultMeasureUnitEnum.UN.value
        is_default_unit = effective_default == i.measureunit_nh

        if is_default_unit:
            factor = 1
            prediction = 1
            probability = 100
        elif show_factors:
            factor = i.factor
            prediction = None
            probability = None
        else:
            factor = None
            prediction = None
            probability = None

        if i.idMeasureUnit == effective_default:
            drug_defaultunit.add(i.id)

        result.append(
            {
                "id": f"{i.id}-{i.idMeasureUnit}",
                "idDrug": i[1],
                "name": escape_html(str(i[2])) if i[2] is not None else None,
                "idMeasureUnit": i[3],
                "factor": factor,
                "measureUnit": escape_html(str(i[5])) if i[5] is not None else None,
                "sctid": escape_html(str(i.sctid)) if i.sctid is not None else None,
                "substanceMeasureUnit": effective_default,
                "drugMeasureUnitNh": i.measureunit_nh,
                "prediction": prediction,
                "probability": probability,
                "prescribedQuantity": i.prescribed_quantity,
                "substanceTags": i.tags,
                "uniformMeasureUnit": i.uniform_measure_unit,
                "substanceName": i.substance_name,
            }
        )

    for i in conversion_list:
        effective_default = i.default_measureunit or DefaultMeasureUnitEnum.UN.value
        if i.id not in drug_defaultunit:
            drug_defaultunit.add(i.id)

            d_unit = default_units.get(effective_default, None)

            if d_unit:
                result.append(
                    {
                        "id": f"{i.id}-{d_unit.get('idMeasureUnit')}",
                        "idDrug": i.id,
                        "name": escape_html(str(i.name))
                        if i.name is not None
                        else None,
                        "idMeasureUnit": d_unit.get("idMeasureUnit"),
                        "factor": 1,
                        "measureUnit": escape_html(str(d_unit.get("description")))
                        if d_unit.get("description") is not None
                        else None,
                        "sctid": escape_html(str(i.sctid))
                        if i.sctid is not None
                        else None,
                        "substanceMeasureUnit": i.default_measureunit
                        if i.default_measureunit
                        else DefaultMeasureUnitEnum.UN.value,
                        "drugMeasureUnitNh": d_unit.get("measureunit_nh", None),
                        "prediction": 1,
                        "probability": 100,
                        "prescribed_quantity": i.prescribed_quantity,
                        "substanceTags": i.tags,
                        "uniformMeasureUnit": i.uniform_measure_unit,
                        "substanceName": i.substance_name,
                    }
                )

    return result


@has_permission(Permission.ADMIN_UNIT_CONVERSION)
def save_conversions(
    id_drug,
    id_segment,
    id_measure_unit_default,
    conversion_list,
    user_context: User,
    wait_for_lambda: bool = False,
    skip_lambda: bool = False,
):
    if (
        id_drug == None
        or id_measure_unit_default == None
        or conversion_list == None
        or len(conversion_list) == 0
    ):
        raise ValidationError(
            "Parâmetros inválidos",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    for uc in conversion_list:
        try:
            factor = float(uc["factor"]) if uc["factor"] is not None else None
            uc["factor"] = factor
        except (ValueError, TypeError):
            raise ValidationError(
                "Fator de conversão deve ser um número válido",
                "errors.invalidParams",
                status.HTTP_400_BAD_REQUEST,
            )

        if uc["factor"] is None or uc["factor"] == 0:
            raise ValidationError(
                "Fator de conversão inválido",
                "errors.invalidParams",
                status.HTTP_400_BAD_REQUEST,
            )

    # update all segments
    updated_segments = []
    segments = db.session.query(Segment).all()

    for s in segments:
        updated_segments.append(s.description)

        # set drug attributes
        da = (
            db.session.query(DrugAttributes)
            .filter(DrugAttributes.idDrug == id_drug)
            .filter(DrugAttributes.idSegment == s.id)
            .first()
        )

        if da is None:
            da = main_drug_service.create_attributes_from_reference(
                id_drug=id_drug, id_segment=s.id, user=user_context
            )

        da.idMeasureUnit = id_measure_unit_default
        da.update = datetime.today()
        da.user = user_context.id

        db.session.flush()

        # update conversions
        _update_conversion_list(
            conversion_list=conversion_list,
            id_drug=id_drug,
            id_segment=s.id,
            user=user_context,
        )

        admin_drug_service.calculate_dosemax_uniq(id_drug=id_drug, id_segment=s.id)

    # call lambda to generate scores
    if skip_lambda:
        return {"updated": updated_segments}

    lambda_client = boto3.client("lambda", region_name=Config.NIFI_SQS_QUEUE_REGION)
    lambda_response = lambda_client.invoke(
        FunctionName=Config.BACKEND_FUNCTION_NAME,
        InvocationType="RequestResponse" if wait_for_lambda else "Event",
        Payload=json.dumps(
            {
                "command": "lambda_scores.process_drug_scores",
                "schema": user_context.schema,
                "id_user": user_context.id,
                "id_drug": id_drug,
            }
        ),
    )

    result = {"updated": updated_segments}

    if wait_for_lambda:
        payload = lambda_response.get("Payload")
        result["lambdaResponse"] = json.loads(payload.read()) if payload else None

    return result


def _update_conversion_list(conversion_list, id_drug, id_segment, user):
    for uc in conversion_list:
        insert_units = text(
            f"""
            insert into {user.schema}.unidadeconverte
                (idsegmento, fkmedicamento, fkunidademedida, fator)
            values
                (:id_segment, :id_drug, :id_measure_unit, :factor)
            on conflict (idsegmento, fkmedicamento, fkunidademedida)
            do update set fator = :factor
        """
        )

        db.session.execute(
            insert_units,
            {
                "id_segment": id_segment,
                "id_drug": id_drug,
                "id_measure_unit": uc["idMeasureUnit"],
                "factor": uc["factor"],
            },
        )


@has_permission(Permission.ADMIN_UNIT_CONVERSION)
def add_default_units(user_context: User):
    schema = user_context.schema

    admin_drug_service.fix_inconsistency()

    query = text(
        f"""
        with unidades as (
            select
                fkmedicamento, min(fkunidademedida) as fkunidademedida
            from (
                select
                    fkmedicamento, fkunidademedida
                from {schema}.prescricaoagg p
                where
                    p.fkunidademedida is not null
                    and p.fkunidademedida <> ''
                    and p.fkmedicamento in (
                        select fkmedicamento from {schema}.medatributos m where m.fkunidademedida is null
                    )
                group by fkmedicamento, fkunidademedida
            ) a
            group by fkmedicamento
            having count(*) = 1
        ), unidades_segmento as (
            select fkmedicamento, fkunidademedida, s.idsegmento  from unidades, {schema}.segmento s
        )
        update
            {schema}.medatributos ma
        set
            fkunidademedida = unidades_segmento.fkunidademedida
        from
            unidades_segmento
        where
            ma.fkmedicamento = unidades_segmento.fkmedicamento
            and ma.idsegmento = unidades_segmento.idsegmento
            and ma.fkunidademedida is null
    """
    )

    insert_units = text(
        f"""
        insert into {schema}.unidadeconverte
            (idsegmento, fkmedicamento, fkunidademedida, fator)
        select
            m.idsegmento, m.fkmedicamento, m.fkunidademedida, 1
        from
            {schema}.medatributos m
        where
            m.fkunidademedida is not null
            and m.fkunidademedida != ''
        on conflict (idsegmento, fkmedicamento, fkunidademedida)
        do nothing
    """
    )

    result = db.session.execute(query)

    db.session.execute(insert_units)

    return result


@has_permission(Permission.ADMIN_UNIT_CONVERSION)
def copy_unit_conversion(id_segment_origin, id_segment_destiny, user_context: User):
    schema = user_context.schema

    if id_segment_origin == None or id_segment_destiny == None:
        raise ValidationError(
            "Segmento Inválido", "errors.invalidRecord", status.HTTP_400_BAD_REQUEST
        )

    if id_segment_origin == id_segment_destiny:
        raise ValidationError(
            "Segmento origem deve ser diferente do segmento destino",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    query = text(
        f"""
        with conversao_origem as (
            select
                ma.fkmedicamento, ma.idsegmento, ma.fkunidademedida
            from
                {schema}.medatributos ma
                inner join {schema}.medatributos madestino on (
                    ma.fkmedicamento = madestino.fkmedicamento
                    and madestino.idsegmento  = :idSegmentDestiny
                    and ma.fkunidademedida = madestino.fkunidademedida
                )
            where
                ma.idsegmento = :idSegmentOrigin
        )
        insert into {schema}.unidadeconverte (idsegmento, fkunidademedida, fator, fkmedicamento) (
            select
                :idSegmentDestiny as idsegmento,
                u.fkunidademedida,
                u.fator,
                u.fkmedicamento
            from
                {schema}.unidadeconverte u
                inner join conversao_origem on (
                    u.fkmedicamento = conversao_origem.fkmedicamento
                    and u.idsegmento = conversao_origem.idsegmento
                )
        )
        on conflict (fkunidademedida, idsegmento, fkmedicamento)
        do update set fator = excluded.fator
    """
    )

    return db.session.execute(
        query,
        {"idSegmentOrigin": id_segment_origin, "idSegmentDestiny": id_segment_destiny},
    )


_LLM_FEW_SHOT_EXAMPLES = """
Examples (diverse cases — study these, do not copy as output):

1. Container = 1 base unit (base="unidade"):
   Drug: "ATRACURIO BESILATO 10MG/ML SOL INJ AMP 5ML", base=unidade
   Units: [{"idMeasureUnit":"AMP"}, {"idMeasureUnit":"ml"}]
   Step-by-step: AMP is a container; 1 AMP = 1 unidade → F=1.
                 ml is sub-container; 1 AMP = 5mL → 1mL = 1/5 unidade → F=0.2.
   → [{"idMeasureUnit":"AMP","factor":1},{"idMeasureUnit":"ml","factor":0.2}]

2. Concentration encoded as mg/mL, multiple containers:
   Drug: "DIPIRONA SODICA 500MG/ML SOL INJ AMP 2ML", base=mg
   Units: [{"idMeasureUnit":"ml"}, {"idMeasureUnit":"AMP"}]
   Step-by-step: ml is sub-container; 500mg/mL → F(ml)=500.
                 AMP is container; 1 AMP=2mL × 500mg/mL=1000mg → F(AMP)=1000.
   → [{"idMeasureUnit":"ml","factor":500},{"idMeasureUnit":"AMP","factor":1000}]

2b. "X mg/Y mL" means total content, not per-mL concentration. UNIDADE is a container
    (never factor=1 when base≠unidade):
   Drug: "METOCLOPRAMIDA 10MG/2ML SOL INJ AMPOLA 2ML", base=mg
   Units: [{"idMeasureUnit":"AMPOLA"}, {"idMeasureUnit":"UNIDADE"}, {"idMeasureUnit":"ml"}]
   Step-by-step: "10MG/2ML" = 10mg TOTAL in 2mL (not 10mg/mL). Concentration = 10÷2 = 5mg/mL.
                 AMPOLA and UNIDADE are both containers of 2mL; 2mL × 5mg/mL = 10mg → F=10.
                 ml: 5mg/mL → F=5.
   → [{"idMeasureUnit":"AMPOLA","factor":10},{"idMeasureUnit":"UNIDADE","factor":10},{"idMeasureUnit":"ml","factor":5}]

3. Bisnaga with size in name, base=unidade — chain sub-units through container:
   Drug: "BETAMETASONA DIPROPIONATO 0,05% CREME BIS 30G", base=unidade
   Units: [{"idMeasureUnit":"BIS"}, {"idMeasureUnit":"g"}, {"idMeasureUnit":"mg"}]
   Step-by-step: BIS = container = 1 unidade → F(BIS)=1.
                 g: 1 BIS=30g=1 unidade → 1g=1/30 unidade → F(g)=0.0333.
                 mg: 30g=30000mg=1 unidade → 1mg=1/30000 unidade → F(mg)=0.0000333.
   → [{"idMeasureUnit":"BIS","factor":1},{"idMeasureUnit":"g","factor":0.0333},{"idMeasureUnit":"mg","factor":0.0000333}]

4. Drops when mL/drop ratio is known from name or notes:
   Drug: "DIPIRONA SODICA 500MG/ML SOL ORAL GOT FR 20ML", base=mg
   Clinical notes: "1 mL = 20 gotas"
   Units: [{"idMeasureUnit":"ml"}, {"idMeasureUnit":"gotas"}, {"idMeasureUnit":"FR"}]
   Step-by-step: ml: 500mg/mL → F(ml)=500.
                 gotas: 500mg/mL ÷ 20 gotas/mL = 25mg/gota → F(gotas)=25.
                 FR: container 20mL × 500mg/mL = 10000mg → F(FR)=10000.
   → [{"idMeasureUnit":"ml","factor":500},{"idMeasureUnit":"gotas","factor":25},{"idMeasureUnit":"FR","factor":10000}]

5. Null when size/concentration is absent:
   Drug: "CREME BASE FR", base=g
   Units: [{"idMeasureUnit":"FR"}, {"idMeasureUnit":"g"}]
   Step-by-step: FR is container; no size in name or notes → cannot determine g per FR → null.
                 g is base unit itself → F(g)=1.
   → [{"idMeasureUnit":"FR","factor":null},{"idMeasureUnit":"g","factor":1}]

6. Concentration + explicit container volume → BOLSA/FA/UNIDADE = total content:
   Drug: "LEVOFLOXACINO 5MG/ML SOLUCAO INJETAVEL BOLSA 100ML", base=mg
   Units: [{"idMeasureUnit":"BOLSA"}, {"idMeasureUnit":"FA"}, {"idMeasureUnit":"UNIDADE"}, {"idMeasureUnit":"ml"}]
   Step-by-step: Name gives concentration (5mg/mL) and container volume (100mL).
                 BOLSA, FA, UNIDADE all refer to the same 100mL container: 5mg/mL × 100mL = 500mg → F=500.
                 ml: 5mg/mL → F=5.
   → [{"idMeasureUnit":"BOLSA","factor":500},{"idMeasureUnit":"FA","factor":500},{"idMeasureUnit":"UNIDADE","factor":500},{"idMeasureUnit":"ml","factor":5}]

7. (NP) or (NAO PADRAO) prefix — dose is still encoded in the name:
   Drug: "NP: BUSPIRONA 10MG", base=mg
   Units: [{"idMeasureUnit":"UNIDADE"}, {"idMeasureUnit":"COMPRIMIDO"}]
   Step-by-step: "(NP)" and "(NAO PADRAO)" mean ambulatorial/outside ward stock — ignore as a prefix.
                 Drug is still BUSPIRONA 10MG: each tablet holds 10mg.
                 UNIDADE and COMPRIMIDO are both tablet containers → F=10.
   → [{"idMeasureUnit":"UNIDADE","factor":10},{"idMeasureUnit":"COMPRIMIDO","factor":10}]

8. Unit name includes volume (e.g. "AMPOLA 5ML") — use it to confirm total content:
   Drug: "ACIDO TRANEXAMICO 250MG/5ML SOLUCAO INJETAVEL AMPOLA", base=mg
   Units: [{"idMeasureUnit":"AMPOLA 5ML"}, {"idMeasureUnit":"MILILITRO"}]
   Step-by-step: "250MG/5ML" = 250mg TOTAL in 5mL (not 250mg per mL).
                 AMPOLA 5ML — the "5ML" in the unit name matches the denominator, confirming total.
                 AMPOLA 5ML: total = 250mg → F=250.
                 MILILITRO: 250mg ÷ 5mL = 50mg/mL → F=50.
   → [{"idMeasureUnit":"AMPOLA 5ML","factor":250},{"idMeasureUnit":"MILILITRO","factor":50}]
"""


def build_conversion_messages(
    drug_name: str,
    substance_name: str,
    default_unit: str,
    units: list[dict],
    clinical_notes: str = "",
) -> tuple[list, str]:
    """Build the (messages, system) tuple for the unit conversion LLM prompt.

    Exported so the validation script can reuse the same prompt without duplication.
    units: list of {"idMeasureUnit": str, "description": str}
    clinical_notes: pre-formatted string, e.g. "Clinical notes: ..." (or empty string)
    """
    units_json = json.dumps(units, ensure_ascii=False)
    notes_block = f"{clinical_notes}\n" if clinical_notes else ""

    user_message = (
        f"{_LLM_FEW_SHOT_EXAMPLES}\n"
        f"--- NOW SOLVE ---\n\n"
        f"Drug name: {drug_name}\n"
        f"Substance: {substance_name}\n"
        f"Base unit (unidade padrão): {default_unit}\n"
        f"{notes_block}"
        f"\nCalculate factor F for each unit below, where:\n"
        f"  dose_in_{default_unit} = prescribed_quantity × F\n\n"
        f"Rules:\n"
        f"1. Container units (UNIDADE, TB, BIS, AMP, AMPOLA, FA, BOLSA, FR, frasco, CMP, COMPRIMIDO, cap, CAPSULA, and variants like 'AMPOLA 5ML' that embed a volume):\n"
        f"   • base='unidade': every container → F = 1.\n"
        f"   • base≠'unidade' (mg, mcg, ml, UI, etc.): F = total {default_unit} inside 1 container.\n"
        f"     Extract dose from name: 'BUSPIRONA 10MG' → UNIDADE/COMPRIMIDO: F=10.\n"
        f"     UNIDADE is a container (tablet/vial) — never assign F=1 when base≠'unidade' "
        f"unless the container genuinely holds exactly 1 {default_unit}.\n"
        f"2. Sub-container units (g, mg, ml, mcg, mL) — F = {default_unit} per 1 of this unit:\n"
        f"   'X mg/mL' in name → per-mL concentration → F(mL) = X.\n"
        f"   'X mg/Y mL' where Y > 1 → total content X in Y mL → F(mL) = X÷Y.\n"
        f"     e.g. '10MG/2ML': F(mL)=5, F(container 2mL)=10.\n"
        f"   'Y g bisnaga/frasco', base=unidade → F(g) = 1/Y.\n"
        f"3. Drops (gotas, gts):\n"
        f"   F = concentration_per_mL ÷ drops_per_mL.\n"
        f"   Example: '40mg/mL, 1mL=40 drops' → F(gotas) = 1.\n"
        f"   If clinical notes explicitly state the drop equivalence, use that value.\n"
        f"4. Return EVERY unit listed — never omit any.\n"
        f"5. Use null only when neither drug name nor clinical notes provide enough info.\n"
        f"   This includes unrecognized abbreviations (e.g. SGA, BSA) that are not standard "
        f"   units — do not guess for unknown abbreviations.\n\n"
        f"Units to convert:\n{units_json}\n\n"
        f'Return a JSON array with one object per input unit: [{{"idMeasureUnit": "ml", "factor": 1.0}}, ...]'
    )

    system = (
        "You are a clinical pharmacist expert in pharmaceutical units of measure. "
        "Your task is to calculate precise numeric conversion factors between medication units. "
        "For each unit, mentally verify: (1) is it a container or sub-container unit? "
        "(2) what size or concentration is encoded in the drug name? "
        "(3) which rule applies? Then output the result. "
        "Respond ONLY with a valid JSON array — no explanation, no markdown, no code fences."
    )

    return [{"role": "user", "content": user_message}], system


@has_permission(Permission.ADMIN_UNIT_CONVERSION)
def get_llm_conversion_suggestions(request_data: AdminUnitConversionLLMRequest):
    """Ask Bedrock Haiku to suggest conversion factors for each unit in the list."""
    row = substance_repository.get_by_id(request_data.sctid)
    if not row:
        raise ValidationError(
            "Substância não encontrada",
            "errors.notFound",
            status.HTTP_404_NOT_FOUND,
        )

    substance, *_ = row
    default_unit = substance.default_measureunit or "un"
    clinical_notes = f"Clinical notes: {substance.admin_text}" if substance.admin_text else ""

    units = [
        {"idMeasureUnit": item.idMeasureUnit, "description": item.description}
        for item in request_data.conversionList
    ]

    messages, system = build_conversion_messages(
        drug_name=request_data.drugName,
        substance_name=substance.name,
        default_unit=default_unit,
        units=units,
        clinical_notes=clinical_notes,
    )

    return _prompt_haiku(messages=messages, system=system)


def _parse_llm_json(raw: str) -> list:
    """Strip markdown fences from raw LLM output and parse as JSON."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, KeyError) as error:
        logger.backend_logger.error("Resposta inválida do serviço de IA: %s", error)
        raise ValidationError(
            "Resposta inválida do serviço de IA",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )


def _prompt_haiku(messages: list, system: str) -> list:
    """Invoke Bedrock Claude Haiku 4.5 and return the parsed JSON list response."""
    session = boto3.session.Session()
    client = session.client("bedrock-runtime", region_name="us-east-1")

    body = json.dumps(
        {
            "max_tokens": 1024,
            "system": system,
            "messages": messages,
            "anthropic_version": "bedrock-2023-05-31",
        }
    )

    try:
        response = client.invoke_model(
            body=body,
            modelId="us.anthropic.claude-haiku-4-5-20251001-v1:0",
            accept="application/json",
            contentType="application/json",
        )
    except Exception:
        raise ValidationError(
            "Serviço de IA indisponível",
            "errors.serviceUnavailable",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    response_body = json.loads(response.get("body").read())
    return _parse_llm_json(response_body["content"][0]["text"])
