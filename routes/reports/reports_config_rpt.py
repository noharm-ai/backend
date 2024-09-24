from flask import Blueprint

from decorators.api_endpoint_decorator import (
    api_endpoint,
    ApiEndpointUserGroup,
    ApiEndpointAction,
)
from services import memory_service

app_rpt_config = Blueprint("app_rpt_config", __name__)


@app_rpt_config.route("/reports/config", methods=["GET"])
@api_endpoint(user_group=ApiEndpointUserGroup.ALL, action=ApiEndpointAction.READ)
def get_config():
    return memory_service.get_reports()
