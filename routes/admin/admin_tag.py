from flask import Blueprint, request

from models.requests.tag_request import TagListRequest, TagUpsertRequest
from decorators.api_endpoint_decorator import api_endpoint
from services.admin import admin_tag_service

app_admin_tag = Blueprint("app_admin_tag", __name__)


@app_admin_tag.route("/admin/tag/list", methods=["POST"])
@api_endpoint()
def get_tags():
    return admin_tag_service.get_tags(request_data=TagListRequest(**request.get_json()))


@app_admin_tag.route("/admin/tag/upsert", methods=["POST"])
@api_endpoint()
def upsert():
    return admin_tag_service.upsert_tag(
        request_data=TagUpsertRequest(**request.get_json())
    )
