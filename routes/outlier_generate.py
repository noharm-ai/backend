import os
from flask import Blueprint, request
from models.main import *
from models.appendix import *
from models.prescription import *
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import text

from services import outlier_service, drug_service
from exception.validation_error import ValidationError

app_gen = Blueprint("app_gen", __name__)


@app_gen.route(
    "/outliers/generate/add-history/<int:id_segment>/<int:id_drug>", methods=["POST"]
)
@jwt_required()
def add_history(id_segment, id_drug):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        rowcount = outlier_service.add_prescription_history(
            id_drug=id_drug,
            id_segment=id_segment,
            schema=user.schema,
            clean=True,
            rollback_when_empty=True,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, rowcount)


@app_gen.route(
    "/outliers/generate/config/<int:id_segment>/<int:id_drug>", methods=["POST"]
)
@jwt_required()
def config(id_segment, id_drug):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"
    data = request.get_json()

    try:
        drug_service.drug_config_to_generate_score(
            id_drug=id_drug,
            id_segment=id_segment,
            id_measure_unit=data.get("idMeasureUnit", None),
            division=data.get("division", None),
            use_weight=data.get("useWeight", False),
            measure_unit_list=data.get("measureUnitList"),
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, True)


@app_gen.route(
    "/outliers/generate/prepare/<int:id_segment>/<int:id_drug>", methods=["POST"]
)
@jwt_required()
def prepare(id_segment, id_drug):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        result = outlier_service.prepare(
            id_drug=id_drug, id_segment=id_segment, user=user
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, result.rowcount)


@app_gen.route(
    "/outliers/generate/single/<int:id_segment>/<int:id_drug>", methods=["POST"]
)
@app_gen.route("/outliers/generate/fold/<int:id_segment>/<int:fold>", methods=["POST"])
@jwt_required()
def generate(id_segment, id_drug=None, fold=None):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        outlier_service.generate(
            id_drug=id_drug, id_segment=id_segment, fold=fold, user=user
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, True)


@app_gen.route(
    "/outliers/generate/remove-outlier/<int:id_segment>/<int:id_drug>", methods=["POST"]
)
@jwt_required()
def remove_outlier(id_segment, id_drug):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        outlier_service.remove_outlier(
            id_drug=id_drug, id_segment=id_segment, user=user
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, True)
