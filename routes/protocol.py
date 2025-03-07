"""Route: protocol related endpoints"""

from flask import Blueprint, request

from services import protocol_service
from models.requests.protocol_request import ProtocolListRequest
from decorators.api_endpoint_decorator import api_endpoint

app_protocol = Blueprint("app_protocol", __name__)


@app_protocol.route("/protocol/list", methods=["GET"])
@api_endpoint()
def list_protocols():
    """List all and filter protocols"""
    return protocol_service.list_protocols(
        request_data=ProtocolListRequest(**request.args)
    )
