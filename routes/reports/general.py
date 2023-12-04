from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from flask_api import status
from models.main import *
from models.appendix import *
from models.segment import *
from models.prescription import *
from services.reports import general_report_service
from exception.validation_error import ValidationError

app_rpt_general = Blueprint("app_rpt_general", __name__)


@app_rpt_general.route("/reports/general/prescription", methods=["GET"])
@jwt_required()
def general_prescription():
    user = User.find(get_jwt_identity())

    try:
        report_data = general_report_service.get_prescription_report(
            user=user, clearCache=request.args.get("clearCache", False)
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, report_data)
