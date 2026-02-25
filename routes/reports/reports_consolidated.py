from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from models.requests.reports_consolidated_request import (
    PatientDayReportRequest,
    PrescriptionReportRequest,
)
from services.reports import reports_consolidated_service

app_rpt_consolidated = Blueprint("app_rpt_consolidated", __name__)


@app_rpt_consolidated.route("/reports/consolidated/patient-day", methods=["POST"])
@api_endpoint()
def get_patient_day_report():
    return reports_consolidated_service.get_patient_day_report(
        request_data=PatientDayReportRequest(**request.get_json())
    )


@app_rpt_consolidated.route("/reports/consolidated/prescription", methods=["POST"])
@api_endpoint()
def get_prescription_report():
    return reports_consolidated_service.get_prescription_report(
        request_data=PrescriptionReportRequest(**request.get_json())
    )
