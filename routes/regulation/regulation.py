from flask import Blueprint, request

from services.regulation import reg_prioritization_service
from decorators.api_endpoint_decorator import api_endpoint

app_regulation = Blueprint("app_regulaton", __name__)


@app_regulation.route("/regulation/prioritization", methods=["POST"])
@api_endpoint()
def prioritization():
    data = request.get_json()

    return reg_prioritization_service.get_prioritization()
