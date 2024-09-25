from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services.admin import admin_relation_service

app_admin_relation = Blueprint("app_admin_relation", __name__)


@app_admin_relation.route("/admin/relation/list", methods=["POST"])
@api_endpoint()
def get_relations():
    data = request.get_json()

    return admin_relation_service.get_relations(
        limit=data.get("limit", 50),
        offset=data.get("offset", 0),
        id_origin_list=data.get("idOriginList", []),
        id_destination_list=data.get("idDestinationList", []),
        kind_list=data.get("kindList", []),
        level=data.get("level", None),
        relation_status=data.get("status", None),
    )


@app_admin_relation.route("/admin/relation", methods=["POST"])
@api_endpoint()
def upsert_relation():
    return admin_relation_service.upsert_relation(
        data=request.get_json(),
    )
