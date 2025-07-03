"""Route: tag related endpoints"""

from flask import Blueprint

from services import lists_service
from decorators.api_endpoint_decorator import api_endpoint

app_lists = Blueprint("app_lists", __name__)


@app_lists.route("/lists/icds", methods=["GET"])
@api_endpoint()
def list_icds():
    """List icds"""
    return lists_service.list_icds()
