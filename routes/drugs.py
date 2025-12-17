"""Routes for drugs related operations"""

from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services import drug_service

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
