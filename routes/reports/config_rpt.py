from flask import Blueprint
from flask_jwt_extended import jwt_required, get_jwt_identity

from models.main import *
from models.appendix import *
from models.segment import *
from models.prescription import *
from services import memory_service
from exception.validation_error import ValidationError

app_rpt_config = Blueprint("app_rpt_config", __name__)


@app_rpt_config.route("/reports/config", methods=["GET"])
@jwt_required()
def get_config():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    try:
        reports = memory_service.get_reports()
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return {
        "status": "success",
        "data": reports,
    }, status.HTTP_200_OK
