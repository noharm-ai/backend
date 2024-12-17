from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services.reports import reports_exams_service

app_rpt_exams = Blueprint("app_rpt_exams", __name__)


@app_rpt_exams.route("/reports/exams/raw", methods=["GET"])
@api_endpoint()
def get_raw_exams():
    return reports_exams_service.get_raw_exams(id_patient=request.args.get("idPatient"))
