"""Repository: prescription presence (multi-viewer heartbeat) operations in DynamoDB"""

from datetime import datetime, timedelta

import boto3
from boto3.dynamodb.conditions import Key

from config import Config
from models.enums import NoHarmENV
from utils import logger, aws

MAX_INACTIVITY_MINUTES = 5
TTL_BUFFER_MINUTES = 10


def _partition_key(schema: str, id_prescription: int) -> str:
    """Build the multi-tenant-safe partition key for a prescription"""
    return f"{schema}:{id_prescription}"


def is_viewer_fresh(
    last_seen_iso: str, now: datetime = None, max_minutes: int = MAX_INACTIVITY_MINUTES
) -> bool:
    """Check whether a viewer's last heartbeat is still within the active window"""
    if not last_seen_iso:
        return False

    now = now or datetime.today()
    minutes = (now - datetime.fromisoformat(last_seen_iso)).total_seconds() / 60

    return minutes <= max_minutes


def record_heartbeat(schema: str, id_prescription: int, user_id: int, user_name: str) -> dict:
    """Upsert a heartbeat for user_id viewing id_prescription"""
    now_iso = datetime.today().isoformat()
    fallback_item = {
        "userId": user_id,
        "userName": user_name,
        "startDate": now_iso,
        "lastSeen": now_iso,
    }

    if Config.ENV == NoHarmENV.TEST.value:
        return fallback_item

    try:
        dynamodb = aws.get_resource("dynamodb", region_name="sa-east-1")
        table = dynamodb.Table(Config.PRESCRIPTION_PRESENCE_TABLE_NAME)
        expires_at = int(
            (
                datetime.today()
                + timedelta(minutes=MAX_INACTIVITY_MINUTES + TTL_BUFFER_MINUTES)
            ).timestamp()
        )

        response = table.update_item(
            Key={
                "schema_fkprescricao": _partition_key(schema, id_prescription),
                "userId": user_id,
            },
            UpdateExpression=(
                "SET userName = :userName, lastSeen = :now, "
                "startDate = if_not_exists(startDate, :now), expiresAt = :expiresAt"
            ),
            ExpressionAttributeValues={
                ":userName": user_name,
                ":now": now_iso,
                ":expiresAt": expires_at,
            },
            ReturnValues="ALL_NEW",
        )

        return dict(response.get("Attributes", fallback_item))
    except Exception as e:
        logger.backend_logger.error(
            f"DynamoDB error recording presence heartbeat for prescription "
            f"{id_prescription} schema {schema}: {str(e)}",
            exc_info=True,
        )
        return fallback_item


def get_active_viewers(schema: str, id_prescription: int) -> list[dict]:
    """Return viewers with a fresh heartbeat for id_prescription"""
    if Config.ENV == NoHarmENV.TEST.value:
        return []

    try:
        dynamodb = aws.get_resource("dynamodb", region_name="sa-east-1")
        table = dynamodb.Table(Config.PRESCRIPTION_PRESENCE_TABLE_NAME)

        response = table.query(
            KeyConditionExpression=Key("schema_fkprescricao").eq(
                _partition_key(schema, id_prescription)
            )
        )
        items = response.get("Items", [])
    except Exception as e:
        logger.backend_logger.error(
            f"DynamoDB error querying presence for prescription "
            f"{id_prescription} schema {schema}: {str(e)}",
            exc_info=True,
        )
        return []

    return [item for item in items if is_viewer_fresh(item.get("lastSeen"))]
