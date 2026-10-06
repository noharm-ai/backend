"""Route: infection control"""

from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from models.requests.infection_control_request import (
    InfectionControlBackfillRequest,
    InfectionControlListRequest,
    InfectionControlReviewRequest,
)
from services.infection_control import (
    antimicrobial_timeline_service,
    infection_control_service,
)

app_infection_control = Blueprint("app_infection_control", __name__)


@app_infection_control.route(
    "/infection-control/antimicrobial-timeline/<int:admission_number>", methods=["GET"]
)
@api_endpoint()
def get_timeline(admission_number: int):
    """Patient data and antimicrobial courses of an admission"""
    return antimicrobial_timeline_service.get_timeline(
        admission_number=admission_number
    )


@app_infection_control.route(
    "/infection-control/admission/<int:admission_number>", methods=["GET"]
)
@api_endpoint()
def get_admission_state(admission_number: int):
    """Infection control follow-up of an admission"""
    return infection_control_service.get_admission_state(
        admission_number=admission_number
    )


@app_infection_control.route("/infection-control/review", methods=["POST"])
@api_endpoint()
def save_review():
    """Record a review of the patient and its antimicrobial evaluations"""
    return infection_control_service.save_review(
        request_data=InfectionControlReviewRequest(**request.get_json())
    )


@app_infection_control.route("/infection-control/admissions", methods=["POST"])
@api_endpoint()
def list_admissions():
    """Followed admissions for the worklist"""
    return infection_control_service.list_admissions(
        request_data=InfectionControlListRequest(**request.get_json())
    )


@app_infection_control.route("/infection-control/backfill", methods=["POST"])
@api_endpoint()
def backfill():
    """Follow the admissions already on antimicrobials (one batch per call)"""
    return infection_control_service.backfill(
        request_data=InfectionControlBackfillRequest(**request.get_json())
    )
