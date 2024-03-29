import os
from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from models.main import *
from models.appendix import *
from models.segment import *
from models.prescription import *
from services.admin import exam_service
from exception.validation_error import ValidationError

app_admin_exam = Blueprint("app_admin_exam", __name__)


@app_admin_exam.route("/admin/exam/copy", methods=["POST"])
@jwt_required()
def copy_exams():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"
    data = request.get_json()

    try:
        result = exam_service.copy_exams(
            id_segment_origin=data.get("idSegmentOrigin", None),
            id_segment_destiny=data.get("idSegmentDestiny", None),
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, result.rowcount)


@app_admin_exam.route("/admin/exam/most-frequent", methods=["GET"])
@jwt_required()
def get_most_frequent():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    try:
        list = exam_service.get_most_frequent(user=user)
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return {
        "status": "success",
        "data": list,
    }, status.HTTP_200_OK


@app_admin_exam.route("/admin/exam/most-frequent/add", methods=["POST"])
@jwt_required()
def add_most_frequent():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"
    data = request.get_json()

    try:
        exam_service.add_most_frequent(
            id_segment=data.get("idSegment", None),
            exam_types=data.get("examTypes", None),
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, True)
