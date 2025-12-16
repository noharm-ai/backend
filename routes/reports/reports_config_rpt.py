"""Route: Reports configuration route."""

from flask import Blueprint

from decorators.api_endpoint_decorator import api_endpoint
from services.reports import reports_general_service

app_rpt_config = Blueprint("app_rpt_config", __name__)


@app_rpt_config.route("/reports/config", methods=["GET"])
@api_endpoint()
def get_config():
    """Get reports configuration."""
    return reports_general_service.get_report_list()
