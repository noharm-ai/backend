"""Repository: reads from the DynamoDB `noharm-store` (Config.NOHARM_STORE_TABLE).

A generic table shared by NoHarm projects: `pk` names the feature, `sk` the item
inside it, and the payload sits in `data`. This project only reads it: the schema
config (pk `schema_params`) is written by the admin project.

The read sits on the prescription view path, so the client fails fast (1s
timeouts, no retry: about 2s at worst) and the caller decides what a failure
means.
"""

from functools import lru_cache

import boto3
from boto3.dynamodb.types import TypeDeserializer
from botocore.config import Config as BotoConfig

from config import Config

_REGION = "sa-east-1"
_BOTO_CONFIG = BotoConfig(
    connect_timeout=1,
    read_timeout=1,
    retries={"total_max_attempts": 1, "mode": "standard"},
)
_DESERIALIZER = TypeDeserializer()


@lru_cache(maxsize=None)
def _get_client():
    """DynamoDB client with short timeouts, cached per container (a low-level
    client is thread-safe, a boto3 resource is not)"""
    return boto3.client("dynamodb", region_name=_REGION, config=_BOTO_CONFIG)


def get_item_data(pk: str, sk: str) -> dict | None:
    """The `data` of the item (pk, sk): None when there is no item, {} when it
    has no data. Numbers come as Decimal. Raises when DynamoDB fails"""
    response = _get_client().get_item(
        TableName=Config.NOHARM_STORE_TABLE,
        Key={"pk": {"S": pk}, "sk": {"S": sk}},
        ProjectionExpression="#data",
        ExpressionAttributeNames={"#data": "data"},
    )

    item = response.get("Item")
    if item is None:
        return None

    if "data" not in item:
        return {}

    return _DESERIALIZER.deserialize(item["data"]) or {}
