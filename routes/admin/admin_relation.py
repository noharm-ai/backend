from flask import Blueprint, request

from decorators.api_endpoint_decorator import (
    api_endpoint,
    ApiEndpointUserGroup,
    ApiEndpointAction,
)
from models.main import User
from services.admin import admin_relation_service

app_admin_relation = Blueprint("app_admin_relation", __name__)


@app_admin_relation.route("/admin/relation/list", methods=["POST"])
@api_endpoint(user_group=ApiEndpointUserGroup.MAINTAINER, action=ApiEndpointAction.READ)
def get_relations(user_context: User):
    data = request.get_json()

    return admin_relation_service.get_relations(
        user=user_context,
        limit=data.get("limit", 50),
        offset=data.get("offset", 0),
        id_origin_list=data.get("idOriginList", []),
        id_destination_list=data.get("idDestinationList", []),
        kind_list=data.get("kindList", []),
        level=data.get("level", None),
        relation_status=data.get("status", None),
    )


@app_admin_relation.route("/admin/relation", methods=["POST"])
@api_endpoint(
    user_group=ApiEndpointUserGroup.MAINTAINER, action=ApiEndpointAction.WRITE
)
def upsert_relation(user_context: User):
    return admin_relation_service.upsert_relation(
        data=request.get_json(),
        user=user_context,
    )
