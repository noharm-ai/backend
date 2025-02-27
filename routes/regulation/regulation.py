"""Route: regulation related operations"""

from flask import Blueprint, request

from services.regulation import reg_prioritization_service, reg_solicitation_service
from decorators.api_endpoint_decorator import api_endpoint
from models.requests.regulation_prioritization_request import (
    RegulationPrioritizationRequest,
)
from models.requests.regulation_movement_request import RegulationMovementRequest
from models.requests.regulation_solicitation_request import (
    RegulationSolicitationRequest,
)

app_regulation = Blueprint("app_regulaton", __name__)


@app_regulation.route("/regulation/prioritization", methods=["POST"])
@api_endpoint()
def prioritization():
    """get solicitation list to prioritize"""
    return reg_prioritization_service.get_prioritization(
        request_data=RegulationPrioritizationRequest(**request.get_json())
    )


@app_regulation.route("/regulation/view/<int:id>", methods=["GET"])
@api_endpoint()
def view(id: int):
    """view solicitation details"""
    return reg_solicitation_service.get_solicitation(id=id)


@app_regulation.route("/regulation/move", methods=["POST"])
@api_endpoint()
def move():
    """move solicitation stage"""
    return reg_solicitation_service.move(
        request_data=RegulationMovementRequest(**request.get_json())
    )


@app_regulation.route("/regulation/create", methods=["POST"])
@api_endpoint()
def create():
    """creates a new solicitation manually"""
    return reg_solicitation_service.create(
        request_data=RegulationSolicitationRequest(**request.get_json())
    )


@app_regulation.route("/regulation/types", methods=["GET"])
@api_endpoint()
def types():
    """get regulation types"""
    return reg_prioritization_service.get_types()
