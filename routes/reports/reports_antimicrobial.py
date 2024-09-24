from flask import Blueprint, request

from decorators.api_endpoint_decorator import (
    api_endpoint,
    ApiEndpointUserGroup,
    ApiEndpointAction,
)
from models.main import User
from services.reports import reports_antimicrobial_service

app_rpt_antimicrobial = Blueprint("app_rpt_antimicrobial", __name__)


@app_rpt_antimicrobial.route("/reports/antimicrobial/history", methods=["GET"])
@api_endpoint(user_group=ApiEndpointUserGroup.ALL, action=ApiEndpointAction.READ)
def get_headers(user_context: User):

    return reports_antimicrobial_service.get_history(
        admission_number=request.args.get("admissionNumber"), user=user_context
    )
