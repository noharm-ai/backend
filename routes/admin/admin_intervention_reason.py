from flask import Blueprint, request

from decorators.api_endpoint_decorator import (
    api_endpoint,
    ApiEndpointUserGroup,
    ApiEndpointAction,
)
from models.main import User
from services.admin import admin_intervention_reason_service

app_admin_interv = Blueprint("app_admin_interv", __name__)


@app_admin_interv.route("/admin/intervention-reason", methods=["GET"])
@api_endpoint(user_group=ApiEndpointUserGroup.MAINTAINER, action=ApiEndpointAction.READ)
def get_records():
    list = admin_intervention_reason_service.get_reasons()

    return admin_intervention_reason_service.list_to_dto(list)


@app_admin_interv.route("/admin/intervention-reason", methods=["POST"])
@api_endpoint(
    user_group=ApiEndpointUserGroup.MAINTAINER, action=ApiEndpointAction.WRITE
)
def upsert_record(user_context: User):
    data = request.get_json()

    reason = admin_intervention_reason_service.upsert_reason(
        data.get("id", None),
        admin_intervention_reason_service.data_to_object(data),
        user_context,
    )

    return admin_intervention_reason_service.list_to_dto(reason)
