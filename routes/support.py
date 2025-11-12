"""Route: support related operations"""

from flask import Blueprint, request

from services import support_service
from decorators.api_endpoint_decorator import api_endpoint

app_support = Blueprint("app_support", __name__)


@app_support.route("/support/create-ticket", methods=["POST"])
@api_endpoint()
def create_ticket():
    """Create a new ticket"""

    return support_service.create_ticket(
        from_url=request.form.get("fromUrl", None),
        category=request.form.get("category", None),
        title=request.form.get("title", None),
        description=request.form.get("description", None),
        filelist=request.files.getlist("fileList[]"),
        nzero_response=request.form.get("nzero_response", None),
        nzero_summary=request.form.get("nzero_summary", None),
    )


@app_support.route("/support/create-closed-ticket", methods=["POST"])
@api_endpoint()
def create_closed_ticket():
    """Create a closed ticket (answered by ai)"""
    data = request.get_json()

    return support_service.create_closed_ticket(
        description=data.get("description", None)
    )


@app_support.route("/support/attachment", methods=["POST"])
@api_endpoint()
def add_attachment():
    """add attachment to a ticket"""
    return support_service.add_attachment(
        files=request.files, id_ticket=request.form.get("id_ticket", None)
    )


@app_support.route("/support/list-tickets/v2", methods=["GET"])
@api_endpoint()
def list_tickets_v2():
    """List tickets"""
    return support_service.list_tickets_v2()


@app_support.route("/support/list-pending", methods=["GET"])
@api_endpoint()
def list_pending():
    """List tickets with pending action"""
    return support_service.list_pending_action()


@app_support.route("/support/ask-n0", methods=["POST"])
@api_endpoint()
def ask_n0():
    """Ask a question to the n0 agent and return the response"""
    data = request.get_json()

    return support_service.ask_n0(question=data.get("question", None))


@app_support.route("/support/ask-n0-form", methods=["POST"])
@api_endpoint()
def ask_n0_form():
    """Ask a question to the n0 form agent and return the response"""
    data = request.get_json()

    return support_service.ask_n0_form(question=data.get("question", None))


@app_support.route("/support/related-articles", methods=["POST"])
@api_endpoint()
def get_related_articles():
    """Get related content from kb articles"""
    data = request.get_json()

    return support_service.get_related_kb(question=data.get("question", None))


@app_support.route("/support/list-requesters", methods=["GET"])
@api_endpoint()
def list_requesters():
    """List users with request permission"""
    return support_service.list_requesters()
