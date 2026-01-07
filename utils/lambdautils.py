"""Utils: lambda function utils"""

import json


def response_to_json(response: dict):
    """Converts a response object to a JSON string."""

    response_json = json.loads(response["Payload"].read().decode("utf-8"))

    if isinstance(response_json, str):
        response_json = json.loads(response_json)

    return response_json
