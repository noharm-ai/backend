"""Route: project navigation related endpoints"""

from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from models.requests.navigation_request import (
    NavCopyPatientRequest,
    NavCreateDischargeSummaryRequest,
)
from services import navigation_service

app_navigation = Blueprint("app_navigation", __name__)


@app_navigation.route("/navigation/copy", methods=["POST"])
@api_endpoint()
def copy_patient():
    """Copy patient to navigation"""
    return navigation_service.copy_patient(
        request_data=NavCopyPatientRequest(**request.get_json())
    )


@app_navigation.route("/navigation/discharge-summary", methods=["POST"])
@api_endpoint()
def create_discharge_summary():
    """Create the discharge summary for a patient already copied to navigation"""
    return navigation_service.create_discharge_summary(
        request_data=NavCreateDischargeSummaryRequest(**request.get_json())
    )
