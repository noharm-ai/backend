"""Route: infection control"""

from flask import Blueprint

from decorators.api_endpoint_decorator import api_endpoint
from services.infection_control import antimicrobial_timeline_service

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
