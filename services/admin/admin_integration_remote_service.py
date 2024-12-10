import re
import boto3
import json
import dateutil as pydateutil
from utils import status
from markupsafe import escape
from datetime import datetime, timedelta
from sqlalchemy import desc
from sqlalchemy.orm import Session
from botocore.exceptions import ClientError
from botocore.config import Config as BotoConfig

from models.main import db, User
from models.appendix import NifiQueue
from utils import dateutils
from models.enums import NifiQueueActionTypeEnum
from exception.validation_error import ValidationError
from decorators.has_permission_decorator import has_permission, Permission
from config import Config


@has_permission(Permission.ADMIN_INTEGRATION_REMOTE)
def get_file_url(schema: str, filename="template") -> tuple[str, str]:
    client = boto3.client("s3")

    cache_data = _get_cache_data(client=client, schema=schema, filename=filename)

    if cache_data["exists"]:
        return (
            client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": Config.NIFI_BUCKET_NAME,
                    "Key": _get_resource_name(schema=schema, filename=filename),
                },
                ExpiresIn=3600,
            ),
            cache_data["updatedAt"],
        )

    return None, None


def _get_resource_name(schema, filename="current"):
    return f"{schema}/{filename}.json"


def _get_cache_data(client, schema, filename="current"):
    try:
        resource_info = client.head_object(
            Bucket=Config.NIFI_BUCKET_NAME,
            Key=_get_resource_name(schema=schema, filename=filename),
        )

        resource_date = pydateutil.parser.parse(
            resource_info["ResponseMetadata"]["HTTPHeaders"]["last-modified"],
        ) - timedelta(hours=3)

        return {
            "exists": True,
            "updatedAt": resource_date.replace(tzinfo=None).isoformat(),
        }
    except ClientError:
        return {"exists": False, "updatedAt": None}


@has_permission(Permission.ADMIN_INTEGRATION_REMOTE)
def get_template_date(user_context: User):
    client = boto3.client("s3")
    cache_data = _get_cache_data(
        client=client, schema=user_context.schema, filename="template"
    )

    if cache_data != None:
        return {"updatedAt": cache_data["updatedAt"]}

    return {"updatedAt": None}


@has_permission(Permission.ADMIN_INTEGRATION_REMOTE)
def get_template(user_context: User):
    template_url, template_updated_at = get_file_url(
        schema=user_context.schema, filename="template"
    )
    status_url, status_updated_at = get_file_url(
        schema=user_context.schema, filename="status"
    )
    diagnostics_url, diagnostics_updated_at = get_file_url(
        schema=user_context.schema, filename="diagnostics"
    )

    if not template_url:
        raise ValidationError(
            "Template encontrado",
            "errors.businessRule",
            status.HTTP_400_BAD_REQUEST,
        )

    if not status_url:
        raise ValidationError(
            "Status não encontrado",
            "errors.businessRule",
            status.HTTP_400_BAD_REQUEST,
        )

    queue = (
        db.session.query(NifiQueue).order_by(desc(NifiQueue.createdAt)).limit(10).all()
    )
    queue_results = []
    for q in queue:
        queue_results.append(
            {
                "id": q.id,
                "url": q.url,
                "body": q.body,
                "method": q.method,
                "responseCode": q.responseCode,
                "response": q.response,
                "extra": q.extra,
                "responseAt": dateutils.to_iso(q.responseAt),
                "createdAt": dateutils.to_iso(q.createdAt),
            }
        )

    return {
        "template": template_url,
        "status": status_url,
        "diagnostics": diagnostics_url,
        "updatedAt": dateutils.to_iso(template_updated_at),
        "queue": queue_results,
    }


@has_permission(Permission.ADMIN_INTEGRATION_REMOTE)
def push_queue_request(
    id_processor: str, action_type: str, data: dict, user_context: User
):
    if id_processor == None and (
        action_type != NifiQueueActionTypeEnum.CUSTOM_CALLBACK.value
        and action_type != NifiQueueActionTypeEnum.REFRESH_TEMPLATE.value
    ):
        raise ValidationError(
            "Entidade inválida",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    valid_actions = []
    for a in NifiQueueActionTypeEnum:
        valid_actions.append(a.value)

    if action_type not in valid_actions:
        raise ValidationError(
            "Ação inválida'",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    queue = _get_new_queue(
        id_processor=id_processor, action_type=action_type, data=data
    )
    queue.extra = {
        "type": escape(action_type),
        "entity": (
            escape(data.get("entity", None))
            if data.get("entity", None) != None
            else None
        ),
        "componentType": (
            escape(data.get("componentType", None))
            if data.get("componentType", None) != None
            else None
        ),
        "idEntity": (
            escape(data.get("idProcessor", None))
            if data.get("idProcessor", None) != None
            else None
        ),
    }
    queue.createdAt = datetime.today()

    db.session.add(queue)
    db.session.flush()

    _send_to_sqs(queue=queue, schema=user_context.schema)

    return {
        "id": queue.id,
        "extra": queue.extra,
        "createdAt": queue.createdAt.isoformat(),
    }


def _send_to_sqs(queue: NifiQueue, schema: str):
    sqs = boto3.client(
        "sqs",
        config=BotoConfig(
            region_name=Config.NIFI_SQS_QUEUE_REGION,
        ),
    )
    response = sqs.get_queue_url(
        QueueName=schema,
    )
    queue_url = response["QueueUrl"]
    body_data = {
        "schema": schema,
        "id": queue.id,
        "url": queue.url,
        "method": queue.method,
        "runStatus": queue.runStatus,
        "body": queue.body if queue.body else {"empty": True},
        "type": queue.extra.get("type", "default"),
    }

    sqs.send_message(
        QueueUrl=queue_url,
        DelaySeconds=10,
        MessageAttributes={
            "schema": {"DataType": "String", "StringValue": schema},
            "type": {"DataType": "String", "StringValue": "request"},
        },
        MessageBody=json.dumps(body_data),
    )


def _get_new_queue(id_processor: str, action_type: str, data: dict):
    queue = NifiQueue()
    queue.runStatus = False
    queue.createdAt = datetime.today()

    if NifiQueueActionTypeEnum.CLEAR_STATE.value == action_type:
        queue.url = f"nifi-api/processors/{escape(id_processor)}/state/clear-requests"
        queue.method = "POST"
    elif NifiQueueActionTypeEnum.SET_STATE.value == action_type:
        queue.url = f"nifi-api/processors/{escape(id_processor)}/diagnostics"
        queue.method = "GET"
        queue.body = {"state": data["state"]}
        queue.runStatus = True
    elif NifiQueueActionTypeEnum.TERMINATE_PROCESS.value == action_type:
        queue.url = f"nifi-api/processors/{escape(id_processor)}/threads"
        queue.method = "DELETE"
    elif NifiQueueActionTypeEnum.REFRESH_STATE.value == action_type:
        endpoint = f"nifi-api/processors/{escape(id_processor)}/diagnostics"
        if data["componentType"] == "CONNECTION":
            endpoint = f"nifi-api/connections/{escape(id_processor)}"

        queue.url = endpoint
        queue.method = "GET"
    elif NifiQueueActionTypeEnum.LIST_QUEUE.value == action_type:
        queue.url = f"nifi-api/flowfile-queues/{escape(id_processor)}/listing-requests"
        queue.method = "POST"
    elif NifiQueueActionTypeEnum.CLEAR_QUEUE.value == action_type:
        queue.url = f"nifi-api/flowfile-queues/{escape(id_processor)}/drop-requests"
        queue.method = "POST"
    elif NifiQueueActionTypeEnum.CUSTOM_CALLBACK.value == action_type:
        queue.url = data["endpoint"]
        queue.method = data["method"]
        _validate_custom_endpoint(data["endpoint"])
    elif NifiQueueActionTypeEnum.REFRESH_TEMPLATE.value == action_type:
        queue.url = f"nifi-api/system-diagnostics"
        queue.method = "GET"

    return queue


@has_permission(Permission.ADMIN_INTEGRATION_REMOTE)
def get_queue_status(id_queue_list, user_context: User):
    queue_results = []
    update_status = False

    engine = db.engines["report"]
    with Session(engine) as session:
        session.connection(
            execution_options={"schema_translate_map": {None: user_context.schema}}
        )
        queue_list = (
            session.query(NifiQueue).filter(NifiQueue.id.in_(id_queue_list)).all()
        )

        for q in queue_list:
            if q.responseCode == status.HTTP_200_OK:
                update_status = True

            queue_results.append(
                {
                    "id": q.id,
                    "url": q.url,
                    "body": q.body,
                    "method": q.method,
                    "extra": q.extra,
                    "responseCode": q.responseCode,
                    "response": q.response,
                    "responseAt": dateutils.to_iso(q.responseAt),
                    "createdAt": dateutils.to_iso(q.createdAt),
                }
            )

    status_url = None
    status_updated_at = None
    if update_status:
        status_url, status_updated_at = get_file_url(
            schema=user_context.schema, filename="status"
        )

    return {
        "queue": queue_results,
        "updateStatus": update_status,
        "statusUrl": status_url,
        "statusUpdatedAt": status_updated_at,
    }


def _validate_custom_endpoint(endpoint: str):
    pattern1 = re.compile(
        "^nifi-api\/flowfile-queues\/[\w-]{36}\/flowfiles\/[\w-]{36}\/content$"
    )
    pattern2 = re.compile(
        "^nifi-api\/flowfile-queues\/[\w-]{36}\/listing-requests\/[\w-]{36}$"
    )

    if pattern1.match(endpoint):
        return True

    if pattern2.match(endpoint):
        return True

    raise ValidationError(
        "Endpoint custom inválido",
        "errors.businessRules",
        status.HTTP_400_BAD_REQUEST,
    )
