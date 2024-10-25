from markupsafe import escape as escape_html
from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services import outlier_service, drug_service

app_out = Blueprint("app_out", __name__)


@app_out.route("/outliers/<int:idSegment>/<int:idDrug>", methods=["GET"])
@api_endpoint()
def getOutliers(idSegment=1, idDrug=1):
    return outlier_service.get_outliers_list(
        id_segment=idSegment,
        id_drug=idDrug,
        frequency=request.args.get("f", None),
        dose=request.args.get("d", None),
    )


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
    )


@app_out.route("/drugs/<int:idDrug>/units", methods=["GET"])
@api_endpoint()
def getUnits(idDrug, idSegment=1):
    return outlier_service.get_drug_outlier_units(
        id_drug=idDrug, id_segment=request.args.get("idSegment", 1)
    )


@app_out.route("/drugs/<int:idSegment>/<int:idDrug>/convertunit", methods=["POST"])
@api_endpoint()
def setDrugUnit(idSegment, idDrug):
    data = request.get_json()

    drug_service.update_convert_factor(
        id_measure_unit=data.get("idMeasureUnit", None),
        id_drug=idDrug,
        id_segment=idSegment,
        factor=data.get("factor", 1),
    )

    return escape_html(data.get("idMeasureUnit", None))


@app_out.route("/drugs/summary/<int:idSegment>/<int:idDrug>", methods=["GET"])
@api_endpoint()
def getDrugSummary(idDrug, idSegment):
    return drug_service.get_drug_summary(
        id_drug=idDrug, id_segment=idSegment, complete=True
    )
