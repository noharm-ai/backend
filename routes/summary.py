from flask import Blueprint, request

from services import summary_service, llm_service
from decorators.api_endpoint_decorator import api_endpoint

app_summary = Blueprint("app_summary", __name__)


@app_summary.route("/summary/<int:admission_number>", methods=["GET"])
@api_endpoint()
def get_structured_info(admission_number):
    mock = request.args.get("mock", False)

    return summary_service.get_structured_info(
        admission_number=admission_number, mock=mock
    )


@app_summary.route("/summary/prompt", methods=["POST"])
@api_endpoint()
def prompt():
    data = request.get_json()

    return llm_service.prompt(data.get("messages", []), options=data)
