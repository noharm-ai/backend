"""Service: AI related operations"""

import json

import boto3

from config import Config
from exception.validation_error import ValidationError
from models.enums import NoHarmENV
from models.main import Drug
from utils import status


def get_substance(drugs: list[Drug]):
    """Infer substances from drug list"""
    if Config.ENV == NoHarmENV.TEST.value:
        return {}

    if len(drugs) == 0:
        raise ValidationError(
            "Nenhum item selecionado",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    drugs_list = []
    for d in drugs:
        drugs_list.append({"id": d.id, "name": d.name})

    lambda_client = boto3.client("lambda", region_name=Config.NIFI_SQS_QUEUE_REGION)
    response = lambda_client.invoke(
        FunctionName=Config.BACKEND_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(
            {
                "command": "lambda_substances.get_substance",
                "drug_list": drugs_list,
            }
        ),
    )

    return json.loads(response["Payload"].read().decode("utf-8"))


def get_substance_by_drug_name(drug_names: list[str]):
    """Infer substances from conciliation drug names"""
    if Config.ENV == NoHarmENV.TEST.value:
        return {}

    if not drug_names:
        return {}

    lambda_client = boto3.client("lambda", region_name=Config.NIFI_SQS_QUEUE_REGION)
    response = lambda_client.invoke(
        FunctionName=Config.BACKEND_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(
            {
                "command": "lambda_substances.get_substance_by_name",
                "drug_names": drug_names,
            }
        ),
    )

    return json.loads(response["Payload"].read().decode("utf-8"))
