from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from models.main import dbSession, User
from services.reports import reports_antimicrobial_service
from exception.validation_error import ValidationError
from utils import status

app_rpt_antimicrobial = Blueprint("app_rpt_antimicrobial", __name__)


@app_rpt_antimicrobial.route("/reports/antimicrobial/history", methods=["GET"])
@jwt_required()
def get_headers():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    try:
        result = reports_antimicrobial_service.get_history(
            admission_number=request.args.get("admissionNumber"), user=user
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return {"status": "success", "data": result}, status.HTTP_200_OK
