from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services.reports import reports_general_service

app_rpt_general = Blueprint("app_rpt_general", __name__)


@app_rpt_general.route("/reports/general/<string:report>", methods=["GET"])
@api_endpoint()
def get_report(report):
    return reports_general_service.get_report(
        report=report,
        filename=request.args.get("filename", "current"),
    )
