from flask import Blueprint, request
from markupsafe import escape as escape_html

from decorators.api_endpoint_decorator import api_endpoint
from services import drug_service, outlier_service

app_out = Blueprint("app_out", __name__)


@app_out.route("/outliers/<int:idOutlier>", methods=["PUT"])
@api_endpoint()
def setManualOutlier(idOutlier):
    data = request.get_json()

    outlier_service.update_outlier(id_outlier=idOutlier, data=data)

    return escape_html(idOutlier)


@app_out.route("/drugs", methods=["GET"])
@app_out.route("/drugs/<int:idSegment>", methods=["GET"])
@api_endpoint()
def getDrugs(idSegment=None):
    return outlier_service.get_outlier_drugs(
        id_segment=idSegment,
        term=request.args.get("q", None),
        id_drug=request.args.getlist("idDrug[]"),
        add_substance=bool(int(request.args.get("addSubstance", 0))),
        group=bool(int(request.args.get("group", 1))),
    )


@app_out.route("/drugs/summary/<int:idSegment>/<int:idDrug>", methods=["GET"])
@api_endpoint()
def getDrugSummary(idDrug, idSegment):
    return drug_service.get_drug_summary(
        id_drug=idDrug,
        id_segment=idSegment,
        complete=True,
        add_all_frequencies=False,
        add_all_units=False,
    )
