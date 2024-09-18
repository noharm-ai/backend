from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from models.main import *
from models.appendix import *
from models.segment import *
from models.prescription import *
from services.reports import reports_general_service
from exception.validation_error import ValidationError

app_rpt_general = Blueprint("app_rpt_general", __name__)


@app_rpt_general.route("/reports/general/<string:report>", methods=["GET"])
@jwt_required()
def get_report(report):
    user = User.find(get_jwt_identity())

    try:
        report_data = reports_general_service.get_report(
            user=user, report=report, filename=request.args.get("filename", "current")
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, report_data)
