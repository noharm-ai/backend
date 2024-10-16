from flask import Blueprint, request

from models.main import db
from services import user_service
from exception.validation_error import ValidationError
from decorators.api_endpoint_decorator import api_endpoint
from utils import sessionutils

app_usr = Blueprint("app_usr", __name__)


@app_usr.route("/user", methods=["PUT"])
@api_endpoint()
def update_user_password():
    data = request.get_json()

    user_service.update_password(
        password=data.get("password", None),
        newpassword=data.get("newpassword", None),
    )

    return True


@app_usr.route("/users/search", methods=["GET"])
@api_endpoint()
def search_users():
    term = request.args.get("term", None)

    return user_service.search_users(term=term)


@app_usr.route("/user/forget", methods=["GET"])
def forgot_password():
    email = request.args.get("email", None)

    try:
        user_service.get_reset_token(email=email, send_email=True)
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return sessionutils.tryCommit(db, True)


@app_usr.route("/user/reset", methods=["POST"])
def reset_password():
    data = request.get_json()

    try:
        user_service.reset_password(
            token=data.get("reset_token", None),
            password=data.get("newpassword", None),
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return sessionutils.tryCommit(db, True)
