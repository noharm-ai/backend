import os
from flask import Blueprint, request, escape
from flask_jwt_extended import jwt_required, get_jwt_identity

from flask_api import status
from models.main import *
from models.appendix import *
from models.segment import *
from models.prescription import *
from services.admin import segment_service
from services import outlier_service
from exception.validation_error import ValidationError

app_admin_segment = Blueprint("app_admin_segment", __name__)


@app_admin_segment.route("/admin/segments", methods=["POST"])
@jwt_required()
def upsert_segment():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        segment_service.upsert_segment(
            id_segment=data.get("idSegment", None),
            description=data.get("description", None),
            active=data.get("active", None),
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, escape(data.get("idSegment")))


@app_admin_segment.route(
    "/admin/segments/departments/<int:id_segment>", methods=["GET"]
)
@jwt_required()
def get_departments(id_segment):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    list = segment_service.get_departments(id_segment)

    return {"status": "success", "data": list}, status.HTTP_200_OK


@app_admin_segment.route("/admin/segments/departments", methods=["POST"])
@jwt_required()
def upsert_department():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        segment_service.update_segment_departments(
            id_segment=data.get("idSegment", None),
            department_list=data.get("departmentList", None),
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, escape(data.get("idSegment")))


@app_admin_segment.route("/admin/segments/outliers/process-list", methods=["POST"])
@jwt_required()
def get_outliers_process_list():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"
    process_list = []

    try:
        process_list = outlier_service.get_outliers_process_list(
            id_segment=data.get("idSegment", None),
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, process_list)
