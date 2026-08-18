from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services.admin import admin_unit_conversion_service

app_admin_unit_conversion = Blueprint("app_admin_unit_conversion", __name__)


@app_admin_unit_conversion.route("/admin/unit-conversion/list", methods=["POST"])
@api_endpoint(is_admin=True)
def get_unit_conversion_list():
    return admin_unit_conversion_service.get_conversion_list()


@app_admin_unit_conversion.route("/admin/unit-conversion/save", methods=["POST"])
@api_endpoint(is_admin=True)
def save_conversions():
    data = request.get_json()

    return admin_unit_conversion_service.save_conversions(
        id_drug=data.get("idDrug", None),
        id_segment=data.get("idSegment", None),
        id_measure_unit_default=data.get("idMeasureUnitDefault", None),
        conversion_list=data.get("conversionList", []),
        wait_for_lambda=data.get("waitForLambda", False),
        skip_lambda=data.get("skipLambda", False),
    )
