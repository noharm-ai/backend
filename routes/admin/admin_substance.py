from flask import Blueprint, request

from models.main import User
from services.admin import admin_substance_service
from decorators.api_endpoint_decorator import (
    api_endpoint,
    ApiEndpointUserGroup,
    ApiEndpointAction,
)

app_admin_subs = Blueprint("app_admin_subs", __name__)


@app_admin_subs.route("/admin/substance/list", methods=["POST"])
@api_endpoint(user_group=ApiEndpointUserGroup.MAINTAINER, action=ApiEndpointAction.READ)
def get_substances(user_context: User):
    data = request.get_json()

    list = admin_substance_service.get_substances(
        user=user_context,
        limit=data.get("limit", 50),
        offset=data.get("offset", 0),
        name=data.get("name", None),
        class_name=data.get("className", None),
        idClassList=data.get("idClassList", []),
        handling_option=data.get("handlingOption", "filled"),
        handling_type_list=data.get("handlingTypeList", []),
        has_class=data.get("hasClass", None),
        has_admin_text=data.get("hasAdminText", None),
    )

    return list


@app_admin_subs.route("/admin/substance", methods=["POST"])
@api_endpoint(
    user_group=ApiEndpointUserGroup.MAINTAINER, action=ApiEndpointAction.WRITE
)
def update_substance(user_context: User):
    subs = admin_substance_service.upsert_substance(
        data=request.get_json(),
        user=user_context,
    )

    return subs
