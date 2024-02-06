import os
from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from models.main import *
from models.appendix import *
from models.segment import *
from models.prescription import *
from services.admin import integration_service, integration_status_service
from exception.validation_error import ValidationError

app_admin_integration = Blueprint("app_admin_integration", __name__)


@app_admin_integration.route("/admin/integration/refresh-agg", methods=["POST"])
@jwt_required()
def refresh_agg():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"
    try:
        result = integration_service.refresh_agg(
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, result.rowcount)


@app_admin_integration.route(
    "/admin/integration/refresh-prescription", methods=["POST"]
)
@jwt_required()
def refresh_prescriptions():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"
    try:
        result = integration_service.refresh_prescriptions(
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, result.rowcount)


@app_admin_integration.route(
    "/admin/integration/init-intervention-reason", methods=["POST"]
)
@jwt_required()
def init_intervention_reason():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"
    try:
        result = integration_service.init_intervention_reason(
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, result.rowcount)


@app_admin_integration.route("/admin/integration/status", methods=["GET"])
@jwt_required()
def get_status():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"
    try:
        result = integration_status_service.get_status(
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, result)


@app_admin_integration.route("/admin/integration/update", methods=["POST"])
@jwt_required()
def update_config():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"
    request_data = request.get_json()

    try:
        result = integration_service.update_integration_config(
            schema=request_data.get("schema", None),
            status=request_data.get("status", None),
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, result)
