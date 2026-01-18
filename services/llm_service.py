import json
import re

import boto3

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import GlobalMemory
from models.enums import GlobalMemoryEnum
from models.main import db
from utils import status


@has_permission(Permission.READ_DISCHARGE_SUMMARY)
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
        and summary_config.value["provider"] != "claude"
        and summary_config.value["provider"] != "maritaca"
        and summary_config.value["provider"] != "llama"
    ):
        raise ValidationError(
            "Configuração inválida",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    if summary_config.value["provider"] == "openai_azure":
        return _prompt_openai(messages=messages)

    if summary_config.value["provider"] == "gpt_oss":
        return _prompt_gpt_oss(messages=messages)

    if summary_config.value["provider"] == "maritaca":
        return _prompt_maritaca(messages=messages, options=options)

    if summary_config.value["provider"] == "claude":
        return _prompt_claude(messages=messages)

    if summary_config.value["provider"] == "llama":
        return _prompt_llama(messages=messages)


def _prompt_openai(messages):
    raise ValidationError(
        "OpenAi not implemented",
        "errors.invalidModule",
        status.HTTP_400_BAD_REQUEST,
    )


def _prompt_maritaca(messages, options={}):
    raise ValidationError(
        "Maritaca not implemented",
        "errors.invalidModule",
        status.HTTP_400_BAD_REQUEST,
    )


def _prompt_claude(messages):
    session = boto3.session.Session()
    client = session.client("bedrock-runtime", region_name="us-east-1")

    body = json.dumps(
        {
            "max_tokens": 1024,
            "messages": messages,
            "anthropic_version": "bedrock-2023-05-31",
        }
    )

    modelId = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    accept = "application/json"
    contentType = "application/json"

    response = client.invoke_model(
        body=body, modelId=modelId, accept=accept, contentType=contentType
    )

    response_body = json.loads(response.get("body").read())

    return {"answer": response_body["content"][0]["text"]}


def _prompt_gpt_oss(messages):
    session = boto3.session.Session()
    client = session.client("bedrock-runtime", region_name="us-east-1")

    body = json.dumps(
        {
            "max_tokens": 1024,
            "messages": messages,
        }
    )

    modelId = "openai.gpt-oss-120b-1:0"
    accept = "application/json"
    contentType = "application/json"

    response = client.invoke_model(
        body=body, modelId=modelId, accept=accept, contentType=contentType
    )

    response_body = json.loads(response.get("body").read())

    response_message = response_body["choices"][0]["message"]["content"]
    response_message = re.sub(
        r"<reasoning>.*?</reasoning>", "", response_message, flags=re.DOTALL
    )

    return {"answer": response_message}


def _prompt_llama(messages):
    session = boto3.session.Session()
    client = session.client("bedrock-runtime", region_name="us-west-2")

    prompt = "<|begin_of_text|>"
    for m in messages:
        prompt += "<|start_header_id|>" + m["role"] + "<|end_header_id|>\n"
        prompt += m["content"] + "<|eot_id|>\n"
    prompt += "<|start_header_id|>assistant<|end_header_id|>"

    body = json.dumps(
        {"prompt": prompt, "max_gen_len": 1024, "temperature": 0.5, "top_p": 0.9}
    )

    modelId = "meta.llama3-1-405b-instruct-v1:0"
    accept = "application/json"
    contentType = "application/json"

    response = client.invoke_model(
        body=body, modelId=modelId, accept=accept, contentType=contentType
    )

    response_body = json.loads(response.get("body").read())

    return {"answer": response_body["generation"]}
