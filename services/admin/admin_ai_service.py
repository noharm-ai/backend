"""Service: AI related operations"""

import json

import boto3

from config import Config
from models.enums import NoHarmENV


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
