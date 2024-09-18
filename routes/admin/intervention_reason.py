import os
from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from utils import status
from models.main import *
from models.appendix import *
from models.segment import *
from models.prescription import *
from services.admin import admin_intervention_reason_service
from exception.validation_error import ValidationError

app_admin_interv = Blueprint("app_admin_interv", __name__)


@app_admin_interv.route("/admin/intervention-reason", methods=["GET"])
@jwt_required()
def get_records():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    list = admin_intervention_reason_service.get_reasons()

    return {
        "status": "success",
        "data": admin_intervention_reason_service.list_to_dto(list),
    }, status.HTTP_200_OK


@app_admin_interv.route("/admin/intervention-reason", methods=["POST"])
@jwt_required()
def upsert_record():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        reason = admin_intervention_reason_service.upsert_reason(
            data.get("id", None), data_to_object(data), user
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, admin_intervention_reason_service.list_to_dto(reason))


def data_to_object(data) -> InterventionReason:
    return InterventionReason(
        description=data.get("name", None),
        mamy=data.get("parentId", None),
        active=data.get("active", False),
        suspension=data.get("suspension", False),
        substitution=data.get("substitution", False),
        customEconomy=data.get("customEconomy", False),
        relation_type=data.get("relationType", 0),
        idHospital=data.get("idHospital", 1),
    )
