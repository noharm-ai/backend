"""Route: antimicrobial timeline"""

from flask import Blueprint

from decorators.api_endpoint_decorator import api_endpoint
from services import antimicrobial_timeline_service

app_antimicrobial = Blueprint("app_antimicrobial", __name__)


@app_antimicrobial.route(
    "/antimicrobial/timeline/<int:admission_number>", methods=["GET"]
)
@api_endpoint()
def get_timeline(admission_number: int):
    """Patient data and antimicrobial courses of an admission"""
    return antimicrobial_timeline_service.get_timeline(
        admission_number=admission_number
    )
