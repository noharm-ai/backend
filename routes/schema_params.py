"""Routes: schema params (DynamoDB noharm-store), read only here: the admin
project edits them"""

from flask import Blueprint

from decorators.api_endpoint_decorator import api_endpoint
from services import schema_params_service

app_schema_params = Blueprint("app_schema_params", __name__)


@app_schema_params.route("/schema-params", methods=["GET"])
@api_endpoint()
def view_schema_params():
    """The schema params of the user's schema (maintainers only)"""
    return schema_params_service.view_schema_params()
