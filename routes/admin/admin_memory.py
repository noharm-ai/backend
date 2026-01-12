from flask import Blueprint, request
from markupsafe import escape as escape_html

from decorators.api_endpoint_decorator import api_endpoint
from services.admin import admin_memory_service

app_admin_memory = Blueprint("app_admin_memory", __name__)


@app_admin_memory.route("/admin/memory/list", methods=["POST"])
@api_endpoint(is_admin=True)
def get_admin_memory_itens():
    data = request.get_json()

    return admin_memory_service.get_admin_entries(kinds=data.get("kinds", []))


@app_admin_memory.route("/admin/memory", methods=["PUT"])
@api_endpoint(is_admin=True)
def update_memory_item():
    data = request.get_json()

    key = admin_memory_service.update_memory(
        key=data.get("key", None),
        kind=data.get("kind", None),
        value=data.get("value", None),
        unique=data.get("unique", False),
    )

    return escape_html(key)
