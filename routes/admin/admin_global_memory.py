"""Route: admin global memory"""

from flask import Blueprint, request
from markupsafe import escape as escape_html

from decorators.api_endpoint_decorator import api_endpoint
from models.requests.admin.admin_global_memory_request import (
    GlobalMemoryItensRequest,
    UpdateGlobalMemoryRequest,
)
from services.admin import admin_global_memory_service

app_admin_global_memory = Blueprint("app_admin_global_memory", __name__)


@app_admin_global_memory.route("/admin/global-memory/list", methods=["POST"])
@api_endpoint(is_admin=True)
def get_admin_memory_itens():
    """Get memory record"""

    return admin_global_memory_service.get_entries(
        request_data=GlobalMemoryItensRequest(**request.get_json())
    )


@app_admin_global_memory.route("/admin/global-memory/update", methods=["POST"])
@api_endpoint(is_admin=True)
def update_memory_item():
    """Update global memory record"""

    key = admin_global_memory_service.update_memory(
        request_data=UpdateGlobalMemoryRequest(**request.get_json())
    )

    return escape_html(key)
