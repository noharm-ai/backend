"""Route: support related operations"""

from flask import Blueprint, request

from services import support_service
from decorators.api_endpoint_decorator import api_endpoint

app_support = Blueprint("app_support", __name__)


@app_support.route("/support/create-ticket", methods=["POST"])
@api_endpoint()
def create_ticket():
    return support_service.create_ticket(
        from_url=request.form.get("fromUrl", None),
        category=request.form.get("category", None),
        title=request.form.get("title", None),
        description=request.form.get("description", None),
        filelist=request.files.getlist("fileList[]"),
    )


@app_support.route("/support/list-tickets/v2", methods=["GET"])
@api_endpoint()
def list_tickets_v2():
    return support_service.list_tickets_v2()


@app_support.route("/support/list-pending", methods=["GET"])
@api_endpoint()
def list_pending():
    """List tickets with pending action"""
    return support_service.list_pending_action()
