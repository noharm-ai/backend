"""Reports: Integration related report endpoints"""

from flask import Blueprint

from decorators.api_endpoint_decorator import api_endpoint
from services.reports import reports_integration_service

app_rpt_integration = Blueprint("app_rpt_integration", __name__)


@app_rpt_integration.route("/reports/integration/nifilint", methods=["GET"])
@api_endpoint()
def get_nifilint():
    """Retrieve the nifilint archive presigned url from S3."""
    return reports_integration_service.get_nifilint()
