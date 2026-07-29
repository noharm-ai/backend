from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services import help_text_service

app_help_text = Blueprint("app_help_text", __name__)


@app_help_text.route("/help-text/<string:key>", methods=["GET"])
@api_endpoint()
def get_help_text(key: str):
    """Get the help text content for a given key."""
    return help_text_service.get_help_text(key=key)


@app_help_text.route("/help-text/<string:key>", methods=["PUT"])
@api_endpoint()
def update_help_text(key: str):
    """Create or update the help text content for a given key."""
    data = request.get_json() or {}

    return help_text_service.update_help_text(key=key, content=data.get("content"))
