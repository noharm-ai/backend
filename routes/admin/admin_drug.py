from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from models.requests.admin.admin_drug_request import AdminDrugListRequest
from services.admin import admin_drug_service

app_admin_drug = Blueprint("app_admin_drug", __name__)


@app_admin_drug.route("/admin/drug/attributes-list", methods=["POST"])
@api_endpoint(is_admin=True)
def get_drug_list():
    return admin_drug_service.get_drug_list(
        request_data=AdminDrugListRequest(**request.get_json())
    )


@app_admin_drug.route("/admin/drug/ref", methods=["GET"])
@api_endpoint(is_admin=True)
def get_drug_ref():
    sctid = request.args.get("sctid", None)

    return admin_drug_service.get_drug_ref(sctid=sctid)


@app_admin_drug.route("/admin/drug/copy-attributes", methods=["POST"])
@api_endpoint(is_admin=True)
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
@api_endpoint(is_admin=True)
def predict_substance():
    return admin_drug_service.predict_substance()


@app_admin_drug.route("/admin/drug/get-missing-substance", methods=["GET"])
@api_endpoint(is_admin=True)
def get_drugs_missing_substance():
    result = admin_drug_service.get_drugs_missing_substance()

    return result


@app_admin_drug.route("/admin/drug/add-new-outlier", methods=["POST"])
@api_endpoint(is_admin=True)
def add_new_outlier():
    result = admin_drug_service.add_new_drugs_to_outlier()

    return result.rowcount


@app_admin_drug.route("/admin/drug/calculate-dosemax", methods=["POST"])
@api_endpoint(is_admin=True)
def calculate_dosemax_bulk():
    return admin_drug_service.calculate_dosemax_bulk()
