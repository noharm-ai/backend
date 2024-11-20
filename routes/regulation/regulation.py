from flask import Blueprint, request

from services.regulation import reg_prioritization_service, reg_solicitation_service
from decorators.api_endpoint_decorator import api_endpoint
from models.requests.regulation_prioritization_request import (
    RegulationPrioritizationRequest,
)

app_regulation = Blueprint("app_regulaton", __name__)


@app_regulation.route("/regulation/prioritization", methods=["POST"])
@api_endpoint()
def prioritization():
    return reg_prioritization_service.get_prioritization(
        request_data=RegulationPrioritizationRequest(**request.get_json())
    )


@app_regulation.route("/regulation/view/<int:id>", methods=["POST"])
@api_endpoint()
def view(id: int):
    return reg_solicitation_service.get_solicitation(id=id)
