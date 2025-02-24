"""Route: Reports configuration route."""

from flask import Blueprint

from decorators.api_endpoint_decorator import api_endpoint
from services import memory_service

app_rpt_config = Blueprint("app_rpt_config", __name__)


@app_rpt_config.route("/reports/config", methods=["GET"])
@api_endpoint()
def get_config():
    """Get reports configuration."""
    return memory_service.get_reports()
