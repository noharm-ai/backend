import os
from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from utils import status
from models.main import User, dbSession, tryCommit, db
from services.admin import admin_relation_service
from exception.validation_error import ValidationError

app_admin_relation = Blueprint("app_admin_relation", __name__)


@app_admin_relation.route("/admin/relation/list", methods=["POST"])
@jwt_required()
def get_relations():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    list = admin_relation_service.get_relations(
        user=user,
        limit=data.get("limit", 50),
        offset=data.get("offset", 0),
        id_origin_list=data.get("idOriginList", []),
        id_destination_list=data.get("idDestinationList", []),
        kind_list=data.get("kindList", []),
    )

    return {"status": "success", "data": list}, status.HTTP_200_OK


@app_admin_relation.route("/admin/relation", methods=["POST"])
@jwt_required()
def upsert_relation():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        rel = admin_relation_service.upsert_relation(
            data=request.get_json(),
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, rel)
