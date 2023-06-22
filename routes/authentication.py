from flask import Blueprint, request, url_for, jsonify
from flask_api import status
from models.main import *
from models.appendix import *
from models.prescription import *
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt_identity,
    get_jwt,
)
from config import Config
from models.enums import NoHarmENV
from services import auth_service
from exception.validation_error import ValidationError

app_auth = Blueprint("app_auth", __name__)


@app_auth.route("/authenticate", methods=["POST"])
def auth():
    data = request.get_json()

    email = data.get("email", None)
    password = data.get("password", None)

    try:
        auth_data = auth_service.auth_local(email, password)
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return auth_data, status.HTTP_200_OK


@app_auth.route("/auth-provider", methods=["POST"])
def auth_provider():
    data = request.get_json()

    if "schema" not in data or "code" not in data:
        return {
            "status": "error",
            "message": "Parâmetro inválido",
        }, status.HTTP_400_BAD_REQUEST

    try:
        auth_data = auth_service.auth_provider(code=data["code"], schema=data["schema"])
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, auth_data)


@app_auth.route("/refresh-token", methods=["POST"])
@jwt_required(refresh=True)
def refreshToken():
    current_user = get_jwt_identity()
    current_claims = get_jwt()

    if "schema" in current_claims:
        claims = {
            "schema": current_claims["schema"],
            "config": current_claims["config"],
        }
    else:
        db_session = db.create_scoped_session()
        user = db_session.query(User).filter(User.id == current_user).first()
        claims = {"schema": user.schema, "config": user.config}

    access_token = create_access_token(identity=current_user, additional_claims=claims)
    return {"access_token": access_token}
