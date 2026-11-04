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
from botocore.config import Config as BotoConfig

from config import Config

_REGION = "sa-east-1"
_BOTO_CONFIG = BotoConfig(
    connect_timeout=1,
    read_timeout=1,
    retries={"total_max_attempts": 1, "mode": "standard"},
)


@lru_cache(maxsize=None)
def _get_resource():
    """DynamoDB resource with short timeouts, cached per container"""
    return boto3.resource("dynamodb", region_name=_REGION, config=_BOTO_CONFIG)


def get_items_data(pk: str, sks: list[str]) -> dict:
    """The `data` of the items (pk, sk) found, keyed by sk; a missing item is left out.
    Raises when DynamoDB fails"""
    if not sks:
        return {}

    table_name = Config.NOHARM_STORE_TABLE
    response = _get_resource().batch_get_item(
        RequestItems={
            table_name: {
                "Keys": [{"pk": pk, "sk": sk} for sk in dict.fromkeys(sks)],
                "ProjectionExpression": "sk, #data",
                "ExpressionAttributeNames": {"#data": "data"},
            }
        }
    )

    if response.get("UnprocessedKeys"):
        raise RuntimeError(f"noharm-store: unprocessed keys for pk {pk}")

    return {
        item["sk"]: item.get("data") or {}
        for item in response.get("Responses", {}).get(table_name, [])
    }
