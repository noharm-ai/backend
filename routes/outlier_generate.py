from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services import drug_service, outlier_service

app_gen = Blueprint("app_gen", __name__)


@app_gen.route("/outliers/generate/refresh-agg", methods=["GET"])
@api_endpoint()
def refresh_agg():
    """Recalculate prescricaoagg data"""
    return outlier_service.refresh_agg()


@app_gen.route("/outliers/generate/segment", methods=["POST"])
@api_endpoint()
def generate_segment_scores():
    data = request.get_json()

    return outlier_service.generate_segment_scores(
        id_segment=data.get("idSegment", None),
    )


@app_gen.route(
    "/outliers/generate/add-history/<int:id_segment>/<int:id_drug>", methods=["POST"]
)
@api_endpoint()
def add_history(id_segment, id_drug):
    return outlier_service.add_prescription_history(
        id_drug=id_drug,
        id_segment=id_segment,
        clean=True,
        rollback_when_empty=True,
    )


@app_gen.route(
    "/outliers/generate/config/<int:id_segment>/<int:id_drug>", methods=["POST"]
)
@api_endpoint()
def config(id_segment, id_drug):
    data = request.get_json()

    drug_service.drug_config_to_generate_score(
        id_drug=id_drug,
        id_segment=id_segment,
        id_measure_unit=data.get("idMeasureUnit", None),
        division=data.get("division", None),
        use_weight=data.get("useWeight", False),
        measure_unit_list=data.get("measureUnitList"),
    )

    return True


@app_gen.route(
    "/outliers/generate/prepare/<int:id_segment>/<int:id_drug>", methods=["POST"]
)
@api_endpoint()
def prepare(id_segment, id_drug):
    result = outlier_service.prepare(id_drug=id_drug, id_segment=id_segment)
    return result.rowcount


@app_gen.route(
    "/outliers/generate/single/<int:id_segment>/<int:id_drug>", methods=["POST"]
)
@app_gen.route("/outliers/generate/fold/<int:id_segment>/<int:fold>", methods=["POST"])
@api_endpoint()
def generate(id_segment, id_drug=None, fold=None):
    outlier_service.generate(id_drug=id_drug, id_segment=id_segment, fold=fold)

    return True


@app_gen.route(
    "/outliers/generate/remove-outlier/<int:id_segment>/<int:id_drug>", methods=["POST"]
)
@api_endpoint()
def remove_outlier(id_segment, id_drug):
    outlier_service.remove_outlier(id_drug=id_drug, id_segment=id_segment)

    return True
