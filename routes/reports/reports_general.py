from flask import Blueprint, request

from decorators.api_endpoint_decorator import (
    api_endpoint,
    ApiEndpointUserGroup,
    ApiEndpointAction,
)
from models.main import User
from services.reports import reports_general_service

app_rpt_general = Blueprint("app_rpt_general", __name__)


@app_rpt_general.route("/reports/general/<string:report>", methods=["GET"])
@api_endpoint(user_group=ApiEndpointUserGroup.ALL, action=ApiEndpointAction.READ)
def get_report(report, user_context: User):
    return reports_general_service.get_report(
        user=user_context,
        report=report,
        filename=request.args.get("filename", "current"),
    )
