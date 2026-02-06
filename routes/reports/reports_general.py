from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services.reports import reports_custom_service, reports_general_service

app_rpt_general = Blueprint("app_rpt_general", __name__)


@app_rpt_general.route("/reports/general/<string:report>", methods=["GET"])
@api_endpoint()
def get_report(report):
    if report == "CUSTOM":
        return reports_custom_service.get_report_link(
            id_report=request.args.get("id_report", None),
            filename=request.args.get("filename", None),
        )

    return reports_general_service.get_report(
        report=report,
        filename=request.args.get("filename", "current"),
    )
