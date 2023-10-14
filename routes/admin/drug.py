import os
from flask import Blueprint, request
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
def get_drug_conversion_list():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    request_data = request.get_json()

    list = drug_service.get_conversion_list(
        has_price_conversion=request_data.get("hasPriceConversion", None),
        has_substance=request_data.get("hasSubstance", None),
        has_default_unit=request_data.get("hasDefaultUnit", None),
        term=request_data.get("term", None),
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
            }
        )

    return {
        "status": "success",
        "count": list[0][9] if list != None else 0,
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

    return tryCommit(db, {"idSegment": id_segment, "idDrug": id_drug, "factor": factor})


@app_admin_drug.route("/admin/drug/add-default-units", methods=["POST"])
@jwt_required()
def add_default_units():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        result = drug_service.add_default_units(user=user)
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, result.rowcount)
