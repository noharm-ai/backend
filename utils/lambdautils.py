"""Utils: lambda function utils"""

import json

from config import Config
from exception.validation_error import ValidationError
from utils import aws, logger, status


def response_to_json(response: dict):
    """Converts a response object to a JSON string."""

    response_json = json.loads(response["Payload"].read().decode("utf-8"))

    if isinstance(response_json, str):
        response_json = json.loads(response_json)

    return response_json


def invoke_backend_function(payload: dict, error_message: str) -> dict:
    """Invoke a backend-private command synchronously and raise a ValidationError when it fails."""

    lambda_client = aws.get_client("lambda", region_name=Config.NIFI_SQS_QUEUE_REGION)
    response = lambda_client.invoke(
        FunctionName=Config.BACKEND_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload),
    )

    response_json = response_to_json(response)

    # FunctionError: the lambda crashed or timed out; "error": the command raised
    if response.get("FunctionError") or (
        isinstance(response_json, dict) and response_json.get("error")
    ):
        logger.backend_logger.error(
            "Error running %s: %s", payload.get("command"), response_json
        )

        raise ValidationError(
            error_message,
            "errors.businessRules",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return response_json
