from flask import Blueprint, request

from services import tag_service
from models.requests.tag_request import TagListRequest
from decorators.api_endpoint_decorator import api_endpoint

app_tag = Blueprint("app_tag", __name__)


@app_tag.route("/tag/list", methods=["GET"])
@api_endpoint()
def list_tags():
    return tag_service.list_tags(request_data=TagListRequest(**request.args))
