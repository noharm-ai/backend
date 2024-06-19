import os
from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from models.main import *
from models.appendix import *
from models.segment import *
from models.prescription import *
from services.admin import (
    integration_remote_service,
)
from exception.validation_error import ValidationError

app_admin_integration_remote = Blueprint("app_admin_integration_remote", __name__)


@app_admin_integration_remote.route(
    "/admin/integration-remote/template", methods=["GET"]
)
@jwt_required()
def get_template():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"
    try:
        result = integration_remote_service.get_template(
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, result)


@app_admin_integration_remote.route(
    "/admin/integration-remote/set-state", methods=["POST"]
)
@jwt_required()
def set_state():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"
    request_data = request.get_json()

    try:
        result = integration_remote_service.set_state(
            id_processor=request_data.get("idProcessor", None),
            state=request_data.get("state", None),
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, result)


@app_admin_integration_remote.route(
    "/admin/integration-remote/queue-status", methods=["GET"]
)
@jwt_required()
def queue_status():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        result = integration_remote_service.get_queue_status(
            id_queue_list=request.args.getlist("idQueueList[]"),
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, result)


@app_admin_integration_remote.route(
    "/admin/integration-remote/push-queue-request", methods=["POST"]
)
@jwt_required()
def push_queue_request():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"
    request_data = request.get_json()

    try:
        result = integration_remote_service.push_queue_request(
            id_processor=request_data.get("idProcessor", None),
            action_type=request_data.get("actionType", None),
            data=request_data,
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, result)
