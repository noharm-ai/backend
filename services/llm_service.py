from openai import AzureOpenAI

from config import Config
from models.main import *
from models.appendix import GlobalMemory
from models.enums import GlobalMemoryEnum
from exception.validation_error import ValidationError


def prompt(messages, options={}):
    if messages == None or len(messages) == 0:
        return ""

    summary_config = (
        db.session.query(GlobalMemory)
        .filter(GlobalMemory.kind == GlobalMemoryEnum.SUMMARY_CONFIG.value)
        .first()
    )

    if summary_config == None or (
        summary_config.value["provider"] != "openai_azure"
        and summary_config.value["provider"] != "maritaca"
    ):
        raise ValidationError(
            "Configuração inválida",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    if summary_config.value["provider"] == "openai_azure":
        return _prompt_openai(messages=messages)

    if summary_config.value["provider"] == "maritaca":
        return _prompt_maritaca(messages=messages, options=options)


def _prompt_openai(messages):
    client = AzureOpenAI(
        api_key=Config.OPEN_AI_API_KEY,
        api_version=Config.OPEN_AI_API_VERSION,
        azure_endpoint=Config.OPEN_AI_API_ENDPOINT,
        timeout=25,
    )

    chat_completion = client.chat.completions.create(
        messages=messages,
        model=Config.OPEN_AI_API_MODEL,
    )

    return {"answer": chat_completion.choices[0].message.content}


def _prompt_maritaca(messages, options={}):
    raise ValidationError(
        "Maritaca not implemented",
        "errors.invalidModule",
        status.HTTP_400_BAD_REQUEST,
    )
