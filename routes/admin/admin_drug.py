from flask import Blueprint, request
from markupsafe import escape as escape_html

from decorators.api_endpoint_decorator import api_endpoint
from services.admin import admin_drug_service

app_admin_drug = Blueprint("app_admin_drug", __name__)


@app_admin_drug.route("/admin/drug/attributes-list", methods=["POST"])
@api_endpoint()
def get_drug_list():
    request_data = request.get_json()

    return admin_drug_service.get_drug_list(
        has_price_conversion=request_data.get("hasPriceConversion", None),
        has_substance=request_data.get("hasSubstance", None),
        has_default_unit=request_data.get("hasDefaultUnit", None),
        has_price_unit=request_data.get("hasPriceUnit", None),
        has_inconsistency=request_data.get("hasInconsistency", None),
        has_missing_conversion=request_data.get("hasMissingConversion", None),
        has_ai_substance=request_data.get("hasAISubstance", None),
        ai_accuracy_range=request_data.get("aiAccuracyRange", None),
        attribute_list=request_data.get("attributeList", []),
        term=request_data.get("term", None),
        substance=request_data.get("substance", None),
        id_segment_list=request_data.get("idSegmentList", None),
        has_max_dose=request_data.get("hasMaxDose", None),
        source_list=request_data.get("sourceList", []),
        limit=request_data.get("limit", 10),
        offset=request_data.get("offset", 0),
        tp_ref_max_dose=request_data.get("tpRefMaxDose", None),
    )


@app_admin_drug.route("/admin/drug/price-factor", methods=["POST"])
@api_endpoint()
def update_price_factor():
    data = request.get_json()

    id_drug = data.get("idDrug", None)
    id_segment = data.get("idSegment", None)
    factor = data.get("factor", None)

    admin_drug_service.update_price_factor(
        id_drug=id_drug,
        id_segment=id_segment,
        factor=factor,
    )

    return {
        "idSegment": escape_html(id_segment),
        "idDrug": escape_html(id_drug),
        "factor": float(factor),
    }


@app_admin_drug.route("/admin/drug/ref", methods=["GET"])
@api_endpoint()
def get_drug_ref():
    sctid = request.args.get("sctid", None)

    return admin_drug_service.get_drug_ref(sctid=sctid)


@app_admin_drug.route("/admin/drug/copy-attributes", methods=["POST"])
@api_endpoint()
def copy_attributes():
    data = request.get_json()

    result = admin_drug_service.copy_drug_attributes(
        id_segment_origin=data.get("idSegmentOrigin", None),
        id_segment_destiny=data.get("idSegmentDestiny", None),
        attributes=data.get("attributes", None),
        from_admin_schema=data.get("fromAdminSchema", True),
        overwrite_all=data.get("overwriteAll", False),
    )

    return result.rowcount


@app_admin_drug.route("/admin/drug/predict-substance", methods=["POST"])
@api_endpoint()
def predict_substance():
    data = request.get_json()

    return admin_drug_service.predict_substance(id_drugs=data.get("idDrugs", []))


@app_admin_drug.route("/admin/drug/get-missing-substance", methods=["GET"])
@api_endpoint()
def get_drugs_missing_substance():
    result = admin_drug_service.get_drugs_missing_substance()

    return result


@app_admin_drug.route("/admin/drug/add-new-outlier", methods=["POST"])
@api_endpoint()
def add_new_outlier():
    result = admin_drug_service.add_new_drugs_to_outlier()

    return result.rowcount


@app_admin_drug.route("/admin/drug/calculate-dosemax", methods=["POST"])
@api_endpoint()
def calculate_dosemax():
    return admin_drug_service.calculate_dosemax()
