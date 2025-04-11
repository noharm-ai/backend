"""Route: admin protocol related endpoints"""

from flask import Blueprint, request

from services.admin import admin_protocol_service
from models.requests.protocol_request import ProtocolListRequest, ProtocolUpsertRequest
from decorators.api_endpoint_decorator import api_endpoint

app_admin_protocol = Blueprint("app_admin_protocol", __name__)


@app_admin_protocol.route("/admin/protocol/list", methods=["POST"])
@api_endpoint()
def list_protocols():
    """List all and filter protocols"""
    return admin_protocol_service.list_protocols(
        request_data=ProtocolListRequest(**request.get_json())
    )


@app_admin_protocol.route("/admin/protocol/upsert", methods=["POST"])
@api_endpoint()
def upsert():
    """Upsert protocol"""
    return admin_protocol_service.upsert_protocol(
        request_data=ProtocolUpsertRequest(**request.get_json())
    )
