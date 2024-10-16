from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services.reports import reports_antimicrobial_service

app_rpt_antimicrobial = Blueprint("app_rpt_antimicrobial", __name__)


@app_rpt_antimicrobial.route("/reports/antimicrobial/history", methods=["GET"])
@api_endpoint()
def get_headers():
    return reports_antimicrobial_service.get_history(
        admission_number=request.args.get("admissionNumber")
    )
