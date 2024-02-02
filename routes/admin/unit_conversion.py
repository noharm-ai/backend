import os
from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from flask_api import status


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

    list = unit_conversion_service.get_conversion_list()

    result = []
    for i in list:
        result.append(
            {
                "idDrug": i[1],
                "name": i[2],
                "idMeasureUnit": i[3],
                "factor": i[4],
                "idSegment": 1,
                "measureUnit": i[5],
            }
        )

    count = 0
    if len(list) > 0:
        count = list[0][0]

    return {
        "status": "success",
        "count": count,
        "data": result,
    }, status.HTTP_200_OK


@app_admin_unit_conversion.route("/admin/unit-conversion/save", methods=["POST"])
@jwt_required()
def get_outliers_process_list():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        unit_conversion_service.save_conversions(
            id_drug=data.get("idDrug", None),
            id_measure_unit_default=data.get("idMeasureUnitDefault", None),
            conversion_list=data.get("conversionList", []),
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, True)
