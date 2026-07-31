"""Route: protocol related endpoints"""

from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from models.requests.protocol_request import (
    ProtocolListRequest,
    ProtocolTestRequest,
    ProtocolTestSampleRequest,
    ProtocolTraceRequest,
)
from services import protocol_service, protocol_trace_service

app_protocol = Blueprint("app_protocol", __name__)


@app_protocol.route("/protocol/list", methods=["GET"])
@api_endpoint()
def list_protocols():
    """List all and filter protocols"""
    return protocol_service.list_protocols(
        request_data=ProtocolListRequest(**request.args)
    )


@app_protocol.route("/protocol/prescription-trace", methods=["GET"])
@api_endpoint()
def trace_protocol():
    """Explain why protocols did or did not activate for a prescription"""
    return protocol_trace_service.trace_protocol(
        request_data=ProtocolTraceRequest(**request.args.to_dict(flat=True))
    )


@app_protocol.route("/protocol/test/sample", methods=["POST"])
@api_endpoint()
def sample_test_prescriptions():
    """Sample prescriptions of the current day to test a protocol config against"""
    return protocol_trace_service.sample_prescriptions(
        request_data=ProtocolTestSampleRequest(**request.get_json())
    )


@app_protocol.route("/protocol/test", methods=["POST"])
@api_endpoint()
def test_protocol_config():
    """Evaluate an unsaved protocol config against a chunk of prescriptions"""
    return protocol_trace_service.test_protocol(
        request_data=ProtocolTestRequest(**request.get_json())
    )
