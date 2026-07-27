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

SOAP_DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
SOAP_DEFAULT_MAX_TOKENS = 4096
SOAP_INPUT_MAX_CHARS = 60000


@has_permission(Permission.READ_NAV)
def generate_soap(request_data: GenerateSoapRequest, user_context: User):
    """Generate a SOAP-format pharmaceutical evolution from a clinical note via LLM."""

    config = _get_config()

    note = (
        db.session.query(ClinicalNotes)
        .options(undefer(ClinicalNotes.form))
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

    return {"text": generated_text}


def _get_config() -> dict:
    """Load SOAP generation config (prompt/model) from global memory."""

    config = (
        db.session.query(GlobalMemory)
        .filter(GlobalMemory.kind == GlobalMemoryEnum.SOAP_CONFIG.value)
        .first()
    )

    if not config or not config.value or not config.value.get("prompt"):
        raise ValidationError(
            "Configuração da evolução SOAP não encontrada.",
            "errors.businessRules",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return config.value


def _get_note_content(note: ClinicalNotes) -> str:
    """Build the LLM user message from the clinical note data."""

    parts = [
        "## Dados da consulta",
        f"Data: {note.date}",
        f"Cargo/Origem: {note.position}",
        f"Responsável: {note.prescriber}",
    ]

    if note.form:
        parts.append("## Formulário da consulta (respostas)")
        parts.append(json.dumps(note.form, ensure_ascii=False, indent=2))

    if note.text:
        parts.append("## Texto da evolução")
        parts.append(note.text[:SOAP_INPUT_MAX_CHARS])

    return "\n\n".join(parts)


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
            modelId=config.get("model_id", SOAP_DEFAULT_MODEL_ID),
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

    return response_body["content"][0]["text"]
