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
