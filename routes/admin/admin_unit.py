from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services.admin import admin_unit_service

app_admin_unit = Blueprint("app_admin_unit", __name__)


@app_admin_unit.route("/admin/unit/list", methods=["POST"])
@api_endpoint(is_admin=True)
def get_units():
    request_data = request.get_json()

    list = admin_unit_service.get_units(
        has_measureunit_nh=request_data.get("hasMeasureUnitNh", None),
    )

    return admin_unit_service.list_to_dto(list)


@app_admin_unit.route("/admin/unit", methods=["PUT"])
@api_endpoint(is_admin=True)
def update_unit():
    data = request.get_json()

    unit = admin_unit_service.update_unit(
        id=data.get("id", None), measureunit_nh=data.get("measureUnitNh", None)
    )

    return admin_unit_service.list_to_dto([unit])
