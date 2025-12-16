"""Route: Custom Reports routes."""

from flask import Blueprint

from decorators.api_endpoint_decorator import api_endpoint
from services.reports import reports_custom_service

app_rpt_custom = Blueprint("app_rpt_custom", __name__)


@app_rpt_custom.route(
    "/reports/custom/download/<int:id_report>/<string:filename>", methods=["GET"]
)
@api_endpoint()
def download(id_report: int, filename: str):
    """Get report presigned url."""
    return reports_custom_service.get_report_link(
        id_report=id_report, filename=filename
    )


@app_rpt_custom.route("/reports/custom/process/<int:id_report>", methods=["GET"])
@api_endpoint()
def process(id_report: int):
    """Process a report."""
    return reports_custom_service.process_report(id_report=id_report)


@app_rpt_custom.route("/reports/custom/list", methods=["GET"])
@api_endpoint()
def get_list():
    """List custom reports."""
    return reports_custom_service.get_report_list()
