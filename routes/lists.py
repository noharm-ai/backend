"""Route: tag related endpoints"""

from flask import Blueprint, request

from services import lists_service
from decorators.api_endpoint_decorator import api_endpoint

app_lists = Blueprint("app_lists", __name__)


@app_lists.route("/lists/icds", methods=["GET"])
@api_endpoint()
def list_icds():
    """List icds"""
    return lists_service.list_icds()


@app_lists.route("/lists/icds/find", methods=["GET"])
@api_endpoint()
def find_icds():
    """Search icds by code or description"""
    term = request.args.get("term", "")

    return lists_service.find_icds(term)


@app_lists.route("/lists/icds/resolve", methods=["GET"])
@api_endpoint()
def resolve_icds():
    """Resolve icds by their codes"""
    ids_param = request.args.get("ids", "")
    ids = [i for i in ids_param.split(",") if i]

    return lists_service.find_icds_by_ids(ids)
