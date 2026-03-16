"""Routes for drugs related operations"""

from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from models.requests.drug_request import DrugUnitConversionRequest
from services import drug_service, unit_conversion_service

app_drugs = Blueprint("app_drugs", __name__)


@app_drugs.route(
    "/drugs/resources/<int:idDrug>/<int:idSegment>/<int:idHospital>", methods=["GET"]
)
@app_drugs.route("/drugs/resources/<int:idDrug>/<int:idSegment>", methods=["GET"])
@api_endpoint()
def getDrugSummary(idDrug, idSegment, idHospital=None):
    return drug_service.get_drug_summary(
        id_drug=idDrug,
        id_segment=idSegment,
        add_all_frequencies=True,
        add_all_units=True,
    )


@app_drugs.route("/drugs/frequencies", methods=["GET"])
@api_endpoint()
def get_frequencies():
    all_frequencies = drug_service.get_all_frequencies()

    results = []
    for f in all_frequencies:
        results.append(
            {
                "id": f[0],
                "description": f[1],
            }
        )

    return results


@app_drugs.route("/drugs/attributes/<int:id_segment>/<int:id_drug>", methods=["GET"])
@api_endpoint()
def get_drug_attributes(id_segment, id_drug):
    return drug_service.get_attributes(id_segment=id_segment, id_drug=id_drug)


@app_drugs.route("/drugs/attributes", methods=["POST"])
@api_endpoint()
def save_drug_attributes():
    data = request.get_json()

    drug_service.save_attributes(
        id_drug=data.get("idDrug", None),
        id_segment=data.get("idSegment", None),
        data=data,
    )

    return True


@app_drugs.route("/drugs/substance", methods=["POST"])
@api_endpoint()
def update_substance():
    data = request.get_json()
    id_drug = data.get("idDrug", None)
    sctid = data.get("sctid", None)

    return drug_service.update_substance(
        id_drug=id_drug,
        sctid=sctid,
    )


@app_drugs.route("/drugs/unit-conversion/<int:id_drug>", methods=["GET"])
@api_endpoint()
def get_unit_conversion(id_drug: int):
    """Get all possible unit conversions for a drug"""

    return unit_conversion_service.get_unit_conversion_for_drug(id_drug=id_drug)


@app_drugs.route("/drugs/unit-conversion/<int:id_drug>", methods=["POST"])
@api_endpoint()
def save_unit_conversion(id_drug: int):
    """Save unit conversion for drug in all segments"""

    return unit_conversion_service.save_unit_conversion_for_drug(
        id_drug=id_drug, request_data=DrugUnitConversionRequest(**request.get_json())
    )


@app_drugs.route("/drugs/process-scores/<int:id_drug>", methods=["POST"])
@api_endpoint()
def process_scores(id_drug: int):
    """Process drug scores"""

    return unit_conversion_service.process_drug_scores(id_drug=id_drug)


@app_drugs.route("/drugs/dashboard/<int:id_segment>/<int:id_drug>", methods=["GET"])
@api_endpoint()
def get_drug_dashboard(id_segment: int, id_drug: int):
    """Get drug data for dashboard"""

    return drug_service.get_drug_dashboard(id_segment=id_segment, id_drug=id_drug)
