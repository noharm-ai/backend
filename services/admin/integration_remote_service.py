import re
from utils import status
from markupsafe import escape
from datetime import datetime
from sqlalchemy import desc

from models.main import User, db
from models.appendix import NifiStatus, NifiQueue
from utils.dateutils import to_iso
from services import permission_service
from models.enums import NifiQueueActionTypeEnum
from exception.validation_error import ValidationError


def get_template_date(user: User):
    if not permission_service.is_admin(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    result = (
        db.session.query(NifiStatus.updatedAt)
        .filter(NifiStatus.nifi_diagnostics != None)
        .filter(NifiStatus.nifi_template != None)
        .filter(NifiStatus.nifi_status != None)
        .first()
    )

    if result != None:
        return {"updatedAt": result.updatedAt.isoformat()}

    return {"updatedAt": None}


def get_template(user: User):
    if not permission_service.is_admin(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    config: NifiStatus = db.session.query(NifiStatus).first()

    if config == None:
        raise ValidationError(
            "Registro não encontrado",
            "errors.businessRule",
            status.HTTP_400_BAD_REQUEST,
        )

    if config.nifi_status == None or config.nifi_template == None:
        raise ValidationError(
            "Template/Status não encontrado",
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
                "responseAt": to_iso(q.responseAt),
                "createdAt": to_iso(q.createdAt),
            }
        )

    return {
        "template": config.nifi_template,
        "status": config.nifi_status,
        "diagnostics": config.nifi_diagnostics,
        "updatedAt": to_iso(config.updatedAt),
        "queue": queue_results,
    }


def push_queue_request(id_processor: str, action_type: str, data: dict, user: User):
    if not permission_service.is_admin(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

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

    return {
        "id": queue.id,
        "extra": queue.extra,
        "createdAt": queue.createdAt.isoformat(),
    }


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


def get_queue_status(id_queue_list, user: User):
    if not permission_service.is_admin(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    queue_list = (
        db.session.query(NifiQueue).filter(NifiQueue.id.in_(id_queue_list)).all()
    )
    queue_results = []
    for q in queue_list:
        queue_results.append(
            {
                "id": q.id,
                "url": q.url,
                "body": q.body,
                "method": q.method,
                "extra": q.extra,
                "responseCode": q.responseCode,
                "response": q.response,
                "responseAt": to_iso(q.responseAt),
                "createdAt": to_iso(q.createdAt),
            }
        )

    return queue_results


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
