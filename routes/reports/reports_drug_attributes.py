from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services.reports import reports_drug_attributes_service

app_rpt_drug_attributes = Blueprint("app_rpt_drug_attributes", __name__)


@app_rpt_drug_attributes.route("/reports/drug-attributes/history", methods=["GET"])
@api_endpoint()
def get_drug_attribute_history():
    return reports_drug_attributes_service.get_history(
        admission_number=request.args.get("admissionNumber"),
        attribute=request.args.get("attribute", "antimicro"),
    )


# Legacy route — kept for backward compatibility, remove once all clients migrate
@app_rpt_drug_attributes.route("/reports/antimicrobial/history", methods=["GET"])
@api_endpoint()
def get_antimicrobial_history_legacy():
    return reports_drug_attributes_service.get_history(
        admission_number=request.args.get("admissionNumber"),
        attribute="antimicro",
    )
