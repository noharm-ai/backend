"""Route: infection control"""

from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from models.requests.infection_control_request import (
    InfectionControlBackfillRequest,
    InfectionControlListRequest,
    InfectionControlReviewRequest,
)
from services.infection_control import (
    infection_control_service,
    recent_cultures_service,
)

app_infection_control = Blueprint("app_infection_control", __name__)


@app_infection_control.route(
    "/infection-control/antimicrobial-timeline/<int:admission_number>", methods=["GET"]
)
@api_endpoint()
def get_timeline(admission_number: int):
    """Patient data, antimicrobial courses and follow-up of an admission"""
    return infection_control_service.get_admission_view(
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


@app_infection_control.route(
    "/infection-control/admission/<int:admission_number>/cultures", methods=["GET"]
)
@api_endpoint()
def get_recent_cultures(admission_number: int):
    """Latest culture of each exam and material of the admission's patient"""
    return recent_cultures_service.get_recent_cultures(
        admission_number=admission_number
    )


@app_infection_control.route(
    "/infection-control/admission/<int:admission_number>/cultures/<int:id_culture>",
    methods=["GET"],
)
@api_endpoint()
def get_culture_history(admission_number: int, id_culture: int):
    """Every culture of the patient with the exam and material of one culture"""
    return recent_cultures_service.get_culture_history(
        admission_number=admission_number, id_culture=id_culture
    )


@app_infection_control.route(
    "/infection-control/admission/<int:admission_number>/follow", methods=["POST"]
)
@api_endpoint()
def follow_admission(admission_number: int):
    """Start following an admission by hand"""
    return infection_control_service.follow_admission(admission_number=admission_number)


@app_infection_control.route("/infection-control/review", methods=["POST"])
@api_endpoint()
def save_review():
    """Record a review of the patient and its antimicrobial evaluations"""
    return infection_control_service.save_review(
        request_data=InfectionControlReviewRequest(**request.get_json())
    )


@app_infection_control.route(
    "/infection-control/non-conformity-reasons", methods=["GET"]
)
@api_endpoint()
def list_non_conformity_reasons():
    """Active reasons of non conformity, to pick from in a review"""
    return infection_control_service.list_non_conformity_reasons()


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
