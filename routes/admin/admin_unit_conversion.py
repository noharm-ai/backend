from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from models.requests.admin.admin_unit_conversion_request import SetFactorRequest
from services.admin import admin_unit_conversion_service

app_admin_unit_conversion = Blueprint("app_admin_unit_conversion", __name__)


@app_admin_unit_conversion.route("/admin/unit-conversion/list", methods=["POST"])
@api_endpoint()
def get_unit_conversion_list():
    request_data = request.get_json()

    return admin_unit_conversion_service.get_conversion_list(
        id_segment=request_data.get("idSegment")
    )


@app_admin_unit_conversion.route("/admin/unit-conversion/predictions", methods=["POST"])
@api_endpoint()
def get_unit_conversion_predictions():
    request_data = request.get_json()

    return admin_unit_conversion_service.get_conversion_predictions(
        conversion_list=request_data.get("conversionList")
    )


@app_admin_unit_conversion.route("/admin/unit-conversion/save", methods=["POST"])
@api_endpoint()
def save_conversions():
    data = request.get_json()

    return admin_unit_conversion_service.save_conversions(
        id_drug=data.get("idDrug", None),
        id_segment=data.get("idSegment", None),
        id_measure_unit_default=data.get("idMeasureUnitDefault", None),
        conversion_list=data.get("conversionList", []),
    )


@app_admin_unit_conversion.route(
    "/admin/unit-conversion/add-default-units", methods=["POST"]
)
@api_endpoint()
def add_default_units():
    result = admin_unit_conversion_service.add_default_units()

    return result.rowcount


@app_admin_unit_conversion.route(
    "/admin/unit-conversion/copy-unit-conversion", methods=["POST"]
)
@api_endpoint()
def copy_unit_conversion():
    data = request.get_json()

    result = admin_unit_conversion_service.copy_unit_conversion(
        id_segment_origin=data.get("idSegmentOrigin", None),
        id_segment_destiny=data.get("idSegmentDestiny", None),
    )

    return result.rowcount


@app_admin_unit_conversion.route(
    "/admin/unit-conversion/substanceunit-factor", methods=["POST"]
)
@api_endpoint()
def set_substanceunit_factor():
    return admin_unit_conversion_service.sut_substanceunit_factor(
        request_data=SetFactorRequest(**request.get_json())
    )
