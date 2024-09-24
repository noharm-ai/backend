from flask import Blueprint, request

from decorators.api_endpoint_decorator import (
    api_endpoint,
    ApiEndpointUserGroup,
    ApiEndpointAction,
)
from models.main import *
from services.admin import admin_unit_conversion_service

app_admin_unit_conversion = Blueprint("app_admin_unit_conversion", __name__)


@app_admin_unit_conversion.route("/admin/unit-conversion/list", methods=["POST"])
@api_endpoint(user_group=ApiEndpointUserGroup.MAINTAINER, action=ApiEndpointAction.READ)
def get_unit_conversion_list(user_context: User):
    request_data = request.get_json()

    return admin_unit_conversion_service.get_conversion_list(
        id_segment=request_data.get("idSegment"),
        user=user_context,
        show_prediction=request_data.get("showPrediction", False),
    )


@app_admin_unit_conversion.route("/admin/unit-conversion/save", methods=["POST"])
@api_endpoint(
    user_group=ApiEndpointUserGroup.MAINTAINER, action=ApiEndpointAction.WRITE
)
def save_conversions(user_context: User):
    data = request.get_json()

    return admin_unit_conversion_service.save_conversions(
        id_drug=data.get("idDrug", None),
        id_segment=data.get("idSegment", None),
        id_measure_unit_default=data.get("idMeasureUnitDefault", None),
        conversion_list=data.get("conversionList", []),
        user=user_context,
    )


@app_admin_unit_conversion.route(
    "/admin/unit-conversion/add-default-units", methods=["POST"]
)
@api_endpoint(
    user_group=ApiEndpointUserGroup.MAINTAINER, action=ApiEndpointAction.WRITE
)
def add_default_units(user_context: User):
    result = admin_unit_conversion_service.add_default_units(user=user_context)

    return result.rowcount


@app_admin_unit_conversion.route(
    "/admin/unit-conversion/copy-unit-conversion", methods=["POST"]
)
@api_endpoint(
    user_group=ApiEndpointUserGroup.MAINTAINER, action=ApiEndpointAction.WRITE
)
def copy_unit_conversion(user_context: User):
    data = request.get_json()

    result = admin_unit_conversion_service.copy_unit_conversion(
        user=user_context,
        id_segment_origin=data.get("idSegmentOrigin", None),
        id_segment_destiny=data.get("idSegmentDestiny", None),
    )

    return result.rowcount
