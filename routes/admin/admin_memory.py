from flask import Blueprint, request
from markupsafe import escape as escape_html

from decorators.api_endpoint_decorator import (
    api_endpoint,
    ApiEndpointUserGroup,
    ApiEndpointAction,
)
from models.main import User
from services.admin import admin_memory_service

app_admin_memory = Blueprint("app_admin_memory", __name__)


@app_admin_memory.route("/admin/memory/list", methods=["POST"])
@api_endpoint(user_group=ApiEndpointUserGroup.MAINTAINER, action=ApiEndpointAction.READ)
def get_admin_memory_itens(user_context: User):
    data = request.get_json()

    return admin_memory_service.get_admin_entries(
        user=user_context, kinds=data.get("kinds", [])
    )


@app_admin_memory.route("/admin/memory", methods=["PUT"])
@api_endpoint(
    user_group=ApiEndpointUserGroup.MAINTAINER, action=ApiEndpointAction.WRITE
)
def update_memory_item(user_context: User):
    data = request.get_json()

    key = admin_memory_service.update_memory(
        key=data.get("key", None),
        kind=data.get("kind", None),
        value=data.get("value", None),
        user=user_context,
        unique=data.get("unique", False),
    )

    return escape_html(key)
