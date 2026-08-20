"""Service: LLM-based SOAP evolution generation from clinical notes"""

import json

from sqlalchemy.orm import undefer

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import GlobalMemory
from models.enums import GlobalMemoryEnum
from models.main import User, db
from models.notes import ClinicalNotes
from models.requests.clinical_notes_request import GenerateSoapRequest
from utils import aws, logger, status

SOAP_DEFAULT_MAX_TOKENS = 4096
SOAP_INPUT_MAX_CHARS = 60000


@has_permission(Permission.READ_NAV)
def generate_soap(request_data: GenerateSoapRequest, user_context: User):
    """Generate a SOAP-format pharmaceutical evolution from a clinical note via LLM."""

    prompts_config = _get_prompts_config()

    if prompts_config:
        config, prompt_key, prompt_options = _resolve_prompt_variant(
            config=prompts_config, prompt_key=request_data.prompt_key
        )
    else:
        config, prompt_key, prompt_options = _get_config(), None, []

    note = (
        db.session.query(ClinicalNotes)
        .options(undefer(ClinicalNotes.form), undefer(ClinicalNotes.template))
        .filter(ClinicalNotes.id == request_data.id)
        .first()
    )

    if not note:
        raise ValidationError(
            "Registro inexistente",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    messages = [
        {
            "role": "user",
            "content": _get_note_content(note),
        }
    ]

    generated_text = _prompt_soap(
        messages=messages, system=config.get("prompt"), config=config
    )

    return {
        "text": generated_text,
        "prompt_key": prompt_key,
        "prompt_options": prompt_options,
    }


def _get_config() -> dict:
    """Load SOAP generation config (prompt/model) from global memory."""

    config = (
        db.session.query(GlobalMemory)
        .filter(GlobalMemory.kind == GlobalMemoryEnum.NAV_SOAP_CONFIG.value)
        .first()
    )

    if (
        not config
        or not config.value
        or not config.value.get("prompt")
        or not config.value.get("model_id")
    ):
        raise ValidationError(
            "Configuração da evolução SOAP não encontrada.",
            "errors.businessRules",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return config.value


def _get_prompts_config() -> dict | None:
    """Load the multi-prompt SOAP config from global memory, if it exists."""

    config = (
        db.session.query(GlobalMemory)
        .filter(GlobalMemory.kind == GlobalMemoryEnum.NAV_SOAP_CONFIG_V2.value)
        .first()
    )

    if not config:
        return None

    prompts = (config.value or {}).get("prompts")

    if not prompts or not isinstance(prompts, list):
        raise ValidationError(
            "Configuração da evolução SOAP não encontrada.",
            "errors.businessRules",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return config.value


def _resolve_prompt_variant(
    config: dict, prompt_key: str | None
) -> tuple[dict, str, list]:
    """Resolve the prompt variant to use and the list of available options."""

    prompts = config.get("prompts")
    options = [{"key": p.get("key"), "label": p.get("label")} for p in prompts]

    key = prompt_key or config.get("default_key") or prompts[0].get("key")

    variant = next((p for p in prompts if p.get("key") == key), None)

    if prompt_key and not variant:
        raise ValidationError(
            "Versão de prompt inválida",
            "errors.invalidParam",
            status.HTTP_400_BAD_REQUEST,
        )

    if not variant or not variant.get("prompt"):
        raise ValidationError(
            "Configuração da evolução SOAP não encontrada.",
            "errors.businessRules",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    model_id = variant.get("model_id") or config.get("model_id")

    if not model_id:
        raise ValidationError(
            "Configuração da evolução SOAP não encontrada.",
            "errors.businessRules",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    resolved = {
        "prompt": variant.get("prompt"),
        "model_id": model_id,
        "max_tokens": variant.get("max_tokens")
        or config.get("max_tokens")
        or SOAP_DEFAULT_MAX_TOKENS,
    }

    return resolved, key, options


def _get_note_content(note: ClinicalNotes) -> str:
    """Build the LLM user message from the clinical note data."""

    parts = [
        "## Dados da consulta",
        f"Data: {note.date}",
        f"Cargo/Origem: {note.position}",
        f"Responsável: {note.prescriber}",
    ]

    if note.form:
        parts.append("## Formulário da consulta (perguntas e respostas)")
        parts.append(_get_form_content(form=note.form, template=note.template))

    if note.text:
        parts.append("## Texto da evolução")
        parts.append(note.text[:SOAP_INPUT_MAX_CHARS])

    return "\n\n".join(parts)


def _get_form_content(form: dict, template: list) -> str:
    """Render form answers as question/answer text using the note template."""

    if not template:
        return json.dumps(form, ensure_ascii=False, indent=2)

    parts = []
    answered = set()

    for group in template:
        group_parts = []

        for question in group.get("questions", []):
            answer = form.get(question.get("id"))

            if answer in (None, "", []):
                continue

            answered.add(question.get("id"))

            if isinstance(answer, list):
                answer = ", ".join(str(item) for item in answer)

            group_parts.append(f"Pergunta: {question.get('label')}")
            group_parts.append(f"Resposta: {answer}")

        if group_parts:
            parts.append(f"### {group.get('group')}")
            parts.extend(group_parts)

    for key, answer in form.items():
        if key not in answered and answer not in (None, "", []):
            parts.append(f"Pergunta: {key}")
            parts.append(f"Resposta: {answer}")

    return "\n".join(parts)


def _prompt_soap(messages: list, system: str, config: dict) -> str:
    """Invoke Bedrock Claude and return the generated SOAP text."""

    client = aws.get_client("bedrock-runtime", region_name="us-east-1")

    body = json.dumps(
        {
            "max_tokens": config.get("max_tokens", SOAP_DEFAULT_MAX_TOKENS),
            "system": system,
            "messages": messages,
            "anthropic_version": "bedrock-2023-05-31",
        }
    )

    try:
        response = client.invoke_model(
            body=body,
            modelId=config.get("model_id"),
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

    return _strip_code_fences(response_body["content"][0]["text"])


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences (```html ... ```) wrapping the LLM output."""

    text = text.strip()

    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""

    if text.endswith("```"):
        text = text[: -len("```")]

    return text.strip()
