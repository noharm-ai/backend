import os
from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from utils import status
from models.main import User, dbSession, tryCommit, db
from services.admin import admin_substance_service
from exception.validation_error import ValidationError

app_admin_subs = Blueprint("app_admin_subs", __name__)


@app_admin_subs.route("/admin/substance/list", methods=["POST"])
@jwt_required()
def get_substances():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    list = admin_substance_service.get_substances(
        user=user,
        limit=data.get("limit", 50),
        offset=data.get("offset", 0),
        name=data.get("name", None),
        class_name=data.get("className", None),
        idClassList=data.get("idClassList", []),
        handling_option=data.get("handlingOption", "filled"),
        handling_type_list=data.get("handlingTypeList", []),
        has_class=data.get("hasClass", None),
        has_admin_text=data.get("hasAdminText", None),
    )

    return {"status": "success", "data": list}, status.HTTP_200_OK


@app_admin_subs.route("/admin/substance", methods=["POST"])
@jwt_required()
def update_substance():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        subs = admin_substance_service.upsert_substance(
            data=request.get_json(),
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, subs)
