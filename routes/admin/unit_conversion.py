import os
from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from utils import status


from models.main import *
from services.admin import unit_conversion_service
from exception.validation_error import ValidationError

app_admin_unit_conversion = Blueprint("app_admin_unit_conversion", __name__)


@app_admin_unit_conversion.route("/admin/unit-conversion/list", methods=["POST"])
@jwt_required()
def get_unit_conversion_list():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"
    request_data = request.get_json()

    list = unit_conversion_service.get_conversion_list(
        id_segment=request_data.get("idSegment"),
        user=user,
        show_prediction=request_data.get("showPrediction", False),
    )

    return {
        "status": "success",
        "data": list,
    }, status.HTTP_200_OK


@app_admin_unit_conversion.route("/admin/unit-conversion/save", methods=["POST"])
@jwt_required()
def save_conversions():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        result = unit_conversion_service.save_conversions(
            id_drug=data.get("idDrug", None),
            id_segment=data.get("idSegment", None),
            id_measure_unit_default=data.get("idMeasureUnitDefault", None),
            conversion_list=data.get("conversionList", []),
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, result)


@app_admin_unit_conversion.route(
    "/admin/unit-conversion/add-default-units", methods=["POST"]
)
@jwt_required()
def add_default_units():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        result = unit_conversion_service.add_default_units(user=user)
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, result.rowcount)


@app_admin_unit_conversion.route(
    "/admin/unit-conversion/copy-unit-conversion", methods=["POST"]
)
@jwt_required()
def copy_unit_conversion():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        result = unit_conversion_service.copy_unit_conversion(
            user=user,
            id_segment_origin=data.get("idSegmentOrigin", None),
            id_segment_destiny=data.get("idSegmentDestiny", None),
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, result.rowcount)
