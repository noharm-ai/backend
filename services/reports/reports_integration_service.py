"""Service: get integration reports"""

import json

import boto3

from decorators.has_permission_decorator import has_permission, Permission
from config import Config


@has_permission(Permission.INTEGRATION_UTILS)
def get_nifilint():
    """Get nifilint report link."""

    lambda_client = boto3.client("lambda", region_name=Config.NIFI_SQS_QUEUE_REGION)
    response = lambda_client.invoke(
        FunctionName=Config.SCORES_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(
            {
                "command": "lambda_nifi_checklist.get_checklist_url",
            }
        ),
    )

    return json.loads(response["Payload"].read().decode("utf-8"))
