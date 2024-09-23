from flask import Blueprint, request

from decorators.api_endpoint_decorator import (
    api_endpoint,
    ApiEndpointUserGroup,
    ApiEndpointAction,
)
from models.main import User
from services.admin import admin_frequency_service

app_admin_freq = Blueprint("app_admin_freq", __name__)


@app_admin_freq.route("/admin/frequency/list", methods=["POST"])
@api_endpoint(user_group=ApiEndpointUserGroup.MAINTAINER, action=ApiEndpointAction.READ)
def get_frequencies():
    request_data = request.get_json()

    list = admin_frequency_service.get_frequencies(
        has_daily_frequency=request_data.get("hasDailyFrequency", None),
    )

    return admin_frequency_service.list_to_dto(list)


@app_admin_freq.route("/admin/frequency", methods=["PUT"])
@api_endpoint(
    user_group=ApiEndpointUserGroup.MAINTAINER, action=ApiEndpointAction.WRITE
)
def update_frequency(user_context: User):
    data = request.get_json()

    freq = admin_frequency_service.update_frequency(
        id=data.get("id", None),
        daily_frequency=data.get("dailyFrequency", None),
        fasting=data.get("fasting", None),
        user=user_context,
    )

    return admin_frequency_service.list_to_dto([freq])
