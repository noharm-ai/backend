"""Service: LLM assistance for protocol trigger expressions"""

import json
import re

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.requests.protocol_request import (
    ProtocolAiGenerateTriggerRequest,
    ProtocolAiReviewTriggerRequest,
)
from utils import aws, logger, status
from utils.alert_protocol import SAFE_LOGICAL_EXPR_REGEX

TRIGGER_AI_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
TRIGGER_AI_MAX_TOKENS = 1024
MAX_TRIGGER_LENGTH = 1000
MAX_TEXT_LENGTH = 600
MAX_REVIEW_FINDINGS = 10
REVIEW_SEVERITIES = {"error", "warning", "info"}

GENERATE_SYSTEM_PROMPT = (
    "You are an assistant embedded in NoHarm, a clinical pharmacy "
    "decision-support system. Users define protocols: alert rules evaluated "
    "against prescriptions. A protocol declares boolean variables (each one "
    "is pre-evaluated by the system to True or False at runtime) and a "
    "trigger expression that combines them.\n\n"
    "Trigger expression language: reference variables as {{name}}, combined "
    'with "and", "or", "not" and parentheses (Python operator precedence: '
    "or < and < not). Nothing else is allowed — no literals, no comparisons, "
    "no function calls.\n\n"
    "The user describes, in Brazilian Portuguese, the rule they want. Build "
    "the trigger expression using ONLY the declared variables listed in the "
    "message. Read each variable's description carefully to pick the right "
    "ones. If a current trigger exists and the user asks for a change to it, "
    "return the complete new expression.\n\n"
    "Respond ONLY with a valid, compact JSON object — no markdown fences, no "
    "extra text — in one of the two forms:\n"
    '{"trigger": "<expression>", "explanation": "<short PT-BR explanation '
    'of the logic>"}\n'
    '{"trigger": null, "explanation": "<PT-BR explanation of why the rule '
    "cannot be expressed with the declared variables, and which variable is "
    'missing>"}\n\n'
    "Rules:\n"
    "- Use ONLY declared variable names. Never invent variables.\n"
    "- Use a variable only when its description matches the clinical concept "
    "in the user's request; when none matches, return the null form instead "
    "of guessing.\n"
    "- Keep the expression as simple as possible; avoid redundant "
    "parentheses.\n"
    "- The explanation must be 1-2 short sentences in Brazilian Portuguese."
)

REVIEW_SYSTEM_PROMPT = (
    "You are a clinical-logic reviewer embedded in NoHarm, a clinical "
    "pharmacy decision-support system. Users define protocols: alert rules "
    "evaluated against prescriptions. A protocol declares boolean variables "
    "(pre-evaluated to True or False at runtime) and a trigger expression "
    'combining them with "and", "or", "not" and parentheses. When the '
    "trigger evaluates to True, the alert message is shown to clinicians.\n\n"
    "You receive the declared variables (name + human description), the "
    "trigger expression and the alert texts. The syntax is already validated "
    "elsewhere — review ONLY the semantics:\n"
    "- contradictions or tautologies (e.g. {{a}} and not {{a}}; branches "
    "that can never or always fire)\n"
    "- redundant or duplicated conditions\n"
    '- connector misuse: an "and"/"or" that contradicts the clinical intent '
    "implied by the variable descriptions and alert texts\n"
    "- declared variables never referenced in the trigger (mention briefly)\n"
    "- mismatch between what the trigger checks and what the alert "
    "message/description claims\n\n"
    "Respond ONLY with a valid, compact JSON object — no markdown fences, no "
    "extra text:\n"
    '{"verdict": "ok" | "attention", "summary": "<1-2 sentence PT-BR overall '
    'assessment>", "findings": [{"severity": "error" | "warning" | "info", '
    '"message": "<PT-BR finding>"}]}\n\n'
    '- "error": logical flaw (contradiction, impossible or always-true '
    "trigger)\n"
    '- "warning": likely mistake or mismatch with the alert texts\n'
    '- "info": minor observation or improvement suggestion\n'
    '- Use verdict "ok" with empty findings when the trigger makes sense. Do '
    "not invent problems."
)


@has_permission(Permission.WRITE_PROTOCOLS)
def generate_trigger(request_data: ProtocolAiGenerateTriggerRequest) -> dict:
    """Ask Bedrock Claude Sonnet to build a trigger expression from a hint."""
    variables_json = json.dumps(
        [
            {"name": v.name, "description": v.summary}
            for v in request_data.variables
        ],
        ensure_ascii=False,
    )

    user_message = (
        f"Declared variables:\n{variables_json}\n\n"
        f"Current trigger expression: {request_data.currentTrigger or '(empty)'}\n\n"
        f"Rule described by the user (PT-BR): {request_data.hint}"
    )

    parsed = _prompt_sonnet(
        messages=[{"role": "user", "content": user_message}],
        system=GENERATE_SYSTEM_PROMPT,
    )

    if not isinstance(parsed, dict):
        _raise_invalid_response()

    explanation = str(parsed.get("explanation") or "").strip()[:MAX_TEXT_LENGTH]
    trigger = parsed.get("trigger")

    if trigger is None or str(trigger).strip() == "":
        return {"trigger": None, "explanation": explanation}

    trigger = str(trigger).strip()[:MAX_TRIGGER_LENGTH]
    _assert_valid_trigger(
        trigger=trigger, variable_names=[v.name for v in request_data.variables]
    )

    return {"trigger": trigger, "explanation": explanation}


@has_permission(Permission.WRITE_PROTOCOLS)
def review_trigger(request_data: ProtocolAiReviewTriggerRequest) -> dict:
    """Ask Bedrock Claude Sonnet to review the semantics of a trigger."""
    variables_json = json.dumps(
        [
            {"name": v.name, "description": v.summary}
            for v in request_data.variables
        ],
        ensure_ascii=False,
    )

    user_message = (
        f"Declared variables:\n{variables_json}\n\n"
        f"Trigger expression: {request_data.trigger}\n\n"
        f"Alert message: {request_data.resultMessage or '(empty)'}\n"
        f"Alert description: {request_data.resultDescription or '(empty)'}"
    )

    parsed = _prompt_sonnet(
        messages=[{"role": "user", "content": user_message}],
        system=REVIEW_SYSTEM_PROMPT,
    )

    return _sanitize_review(parsed)


def _assert_valid_trigger(trigger: str, variable_names: list[str]):
    """Reject generated triggers referencing unknown variables or bad syntax."""
    substituted = trigger
    for name in variable_names:
        substituted = substituted.replace("{{" + name + "}}", "True")

    valid = bool(re.match(SAFE_LOGICAL_EXPR_REGEX, substituted))

    if valid:
        try:
            compile(substituted, "<trigger>", "eval")
        except SyntaxError:
            valid = False

    if not valid:
        logger.backend_logger.error(
            "Serviço de IA gerou expressão inválida: %s", trigger
        )
        raise ValidationError(
            "O serviço de IA gerou uma expressão inválida. Tente novamente.",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )


def _sanitize_review(parsed) -> dict:
    """Discard anything outside the expected review response shape."""
    if not isinstance(parsed, dict):
        _raise_invalid_response()

    verdict = parsed.get("verdict")
    if verdict not in {"ok", "attention"}:
        verdict = "attention"

    summary = str(parsed.get("summary") or "").strip()[:MAX_TEXT_LENGTH]

    findings = []
    raw_findings = parsed.get("findings")
    for raw in raw_findings if isinstance(raw_findings, list) else []:
        if not isinstance(raw, dict):
            continue

        message = str(raw.get("message") or "").strip()
        if not message:
            continue

        severity = raw.get("severity")
        findings.append(
            {
                "severity": severity if severity in REVIEW_SEVERITIES else "info",
                "message": message[:MAX_TEXT_LENGTH],
            }
        )

        if len(findings) >= MAX_REVIEW_FINDINGS:
            break

    return {"verdict": verdict, "summary": summary, "findings": findings}


def _raise_invalid_response():
    raise ValidationError(
        "Resposta inválida do serviço de IA",
        "errors.invalidParams",
        status.HTTP_400_BAD_REQUEST,
    )


def _parse_llm_json(raw: str):
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
        _raise_invalid_response()


def _prompt_sonnet(messages: list, system: str):
    """Invoke Bedrock Claude Sonnet and return the parsed JSON response."""
    client = aws.get_client("bedrock-runtime", region_name="us-east-1")

    body = json.dumps(
        {
            "max_tokens": TRIGGER_AI_MAX_TOKENS,
            "system": system,
            "messages": messages,
            "anthropic_version": "bedrock-2023-05-31",
        }
    )

    try:
        response = client.invoke_model(
            body=body,
            modelId=TRIGGER_AI_MODEL_ID,
            accept="application/json",
            contentType="application/json",
        )
    except Exception as error:
        logger.backend_logger.error("Serviço de IA indisponível: %s", error)
        raise ValidationError(
            "Serviço de IA indisponível",
            "errors.serviceUnavailable",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    response_body = json.loads(response.get("body").read())
    return _parse_llm_json(response_body["content"][0]["text"])
