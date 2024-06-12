from models.main import *
from models.appendix import *
from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from .utils import tryCommit

from services import user_service, user_admin_service
from exception.validation_error import ValidationError


app_user_crud = Blueprint("app_user_crud", __name__)


@app_user_crud.route("/editUser", methods=["POST"])
@jwt_required()
def upsert_user():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    try:
        result = user_admin_service.upsert_user(data=data, user=user)
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, result)


@app_user_crud.route("/users", methods=["GET"])
@jwt_required()
def getUsers():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    try:
        result = user_admin_service.get_user_list(user=user)
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return {"status": "success", "data": result}, status.HTTP_200_OK


@app_user_crud.route("/user/reset-token", methods=["POST"])
@jwt_required()
def get_reset_token():
    data = request.get_json()

    try:
        token = user_service.admin_get_reset_token(data.get("idUser", None))
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, token)
