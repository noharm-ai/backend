import re
from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from models.main import *
from models.appendix import *
from services import user_service
from .utils import tryCommit
from exception.validation_error import ValidationError

app_usr = Blueprint("app_usr", __name__)


@app_usr.route("/user", methods=["PUT"])
@jwt_required()
def update_user_password():
    data = request.get_json()

    try:
        user_service.update_password(
            password=data.get("password", None),
            newpassword=data.get("newpassword", None),
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, True)


@app_usr.route("/user/forget", methods=["GET"])
def forgot_password():
    email = request.args.get("email", None)

    try:
        user_service.get_reset_token(email=email, send_email=True)
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, True)


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

    return tryCommit(db, True)


@app_usr.route("/users/search", methods=["GET"])
@jwt_required()
def search_users():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    term = request.args.get("term", None)

    users = (
        User.query.filter(User.schema == user.schema)
        .filter(
            or_(
                ~User.config["roles"].astext.contains("suporte"),
                User.config["roles"] == None,
            )
        )
        .filter(User.name.ilike("%" + str(term) + "%"))
        .order_by(desc(User.active), asc(User.name))
        .all()
    )

    results = []
    for u in users:
        results.append({"id": u.id, "name": u.name})

    return {"status": "success", "data": results}, status.HTTP_200_OK
