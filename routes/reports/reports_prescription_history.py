from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services.reports import reports_prescription_history_service

app_rpt_prescription_history = Blueprint("app_rpt_prescription_history", __name__)


@app_rpt_prescription_history.route("/reports/prescription/history", methods=["GET"])
@api_endpoint()
def get_data():
    return reports_prescription_history_service.get_prescription_history(
        id_prescription=request.args.get("idPrescription")
    )
