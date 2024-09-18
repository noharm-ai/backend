import os
from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from models.main import db, dbSession, User
from exception.validation_error import ValidationError
from routes.utils import tryCommit
from utils import status
from services import conciliation_service

app_conciliation = Blueprint("app_conciliation", __name__)


@app_conciliation.route("/conciliation/create", methods=["POST"])
@jwt_required()
def create_conciliation():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        id = conciliation_service.create_conciliation(
            admission_number=data.get("admissionNumber", None), user=user
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, str(id), user.permission())


@app_conciliation.route("/conciliation/list-available", methods=["GET"])
@jwt_required()
def list_available():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        result = conciliation_service.list_available(
            admission_number=request.args.get("admissionNumber", None), user=user
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return {
        "status": "success",
        "data": result,
    }, status.HTTP_200_OK
