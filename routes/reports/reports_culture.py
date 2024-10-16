from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services.reports import reports_culture_service

app_rpt_culture = Blueprint("app_rpt_culture", __name__)


@app_rpt_culture.route("/reports/culture", methods=["GET"])
@api_endpoint()
def get_headers():
    return reports_culture_service.get_cultures(idPatient=request.args.get("idPatient"))
