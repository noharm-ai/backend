import os
from flask import Blueprint, request, escape as escape_html
from flask_jwt_extended import jwt_required, get_jwt_identity

from flask_api import status
from models.main import *
from models.appendix import *
from models.segment import *
from models.prescription import *
from services.admin import drug_service
from exception.validation_error import ValidationError

app_admin_drug = Blueprint("app_admin_drug", __name__)


@app_admin_drug.route("/admin/drug/attributes-list", methods=["POST"])
@jwt_required()
def get_drug_list():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    request_data = request.get_json()

    list = drug_service.get_drug_list(
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
        limit=request_data.get("limit", 10),
        offset=request_data.get("offset", 0),
    )

    result = []
    for i in list:
        result.append(
            {
                "idDrug": i[0],
                "name": i[1],
                "idSegment": i[2],
                "segment": i[3],
                "idMeasureUnitDefault": i[4],
                "idMeasureUnitPrice": i[5],
                "measureUnitPriceFactor": i[8],
                "price": i[6],
                "sctid": i[7],
                "substance": i[10],
                "segmentOutlier": i[11],
                "substanceAccuracy": i[12],
            }
        )

    count = 0
    if len(list) > 0:
        count = list[0][9]

    return {
        "status": "success",
        "count": count,
        "data": result,
    }, status.HTTP_200_OK


@app_admin_drug.route("/admin/drug/price-factor", methods=["POST"])
@jwt_required()
def update_price_factor():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    id_drug = data.get("idDrug", None)
    id_segment = data.get("idSegment", None)
    factor = data.get("factor", None)

    try:
        drug_service.update_price_factor(
            id_drug=id_drug,
            id_segment=id_segment,
            factor=factor,
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(
        db,
        {
            "idSegment": escape_html(id_segment),
            "idDrug": escape_html(id_drug),
            "factor": float(factor),
        },
    )


@app_admin_drug.route("/admin/drug/copy-attributes", methods=["POST"])
@jwt_required()
def copy_attributes():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        result = drug_service.copy_drug_attributes(
            user=user,
            id_segment_origin=data.get("idSegmentOrigin", None),
            id_segment_destiny=data.get("idSegmentDestiny", None),
            attributes=data.get("attributes", None),
            from_admin_schema=data.get("fromAdminSchema", True),
            overwrite_all=data.get("overwriteAll", False),
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, result.rowcount)


@app_admin_drug.route("/admin/drug/predict-substance", methods=["POST"])
@jwt_required()
def predict_substance():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        result = drug_service.predict_substance(data.get("idDrugs", []), user)
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, result)


@app_admin_drug.route("/admin/drug/get-missing-substance", methods=["GET"])
@jwt_required()
def get_drugs_missing_substance():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        result = drug_service.get_drugs_missing_substance()
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return {
        "status": "success",
        "count": len(result),
        "data": result,
    }, status.HTTP_200_OK
