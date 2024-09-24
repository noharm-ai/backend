from flask import Blueprint, request

from decorators.api_endpoint_decorator import (
    api_endpoint,
    ApiEndpointUserGroup,
    ApiEndpointAction,
)
from models.main import User
from services.reports import reports_culture_service

app_rpt_culture = Blueprint("app_rpt_culture", __name__)


@app_rpt_culture.route("/reports/culture", methods=["GET"])
@api_endpoint(user_group=ApiEndpointUserGroup.ALL, action=ApiEndpointAction.READ)
def get_headers(user_context: User):
    return reports_culture_service.get_cultures(
        idPatient=request.args.get("idPatient"), user=user_context
    )
