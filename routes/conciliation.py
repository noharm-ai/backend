from flask import Blueprint, request
from markupsafe import escape


from services import conciliation_service
from decorators.api_endpoint_decorator import api_endpoint

app_conciliation = Blueprint("app_conciliation", __name__)


@app_conciliation.route("/conciliation/create", methods=["POST"])
@api_endpoint()
def create_conciliation():
    data = request.get_json()

    id = conciliation_service.create_conciliation(
        admission_number=data.get("admissionNumber", None)
    )

    return escape(str(id))


@app_conciliation.route("/conciliation/list-available", methods=["GET"])
@api_endpoint()
def list_available():
    return conciliation_service.list_available(
        admission_number=request.args.get("admissionNumber", None)
    )
