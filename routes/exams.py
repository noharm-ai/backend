"""Exams routes module"""

from flask import Blueprint, request

from models.requests.exam_request import ExamCreateRequest, ExamDeleteRequest
from services import exams_service
from decorators.api_endpoint_decorator import api_endpoint

app_exams = Blueprint("app_exams", __name__)


@app_exams.route("/exams/create", methods=["POST"])
@api_endpoint()
def create_exam():
    """Creates a new exam"""

    return exams_service.create_exam(
        request_data=ExamCreateRequest(**request.get_json())
    )


@app_exams.route("/exams/delete", methods=["POST"])
@api_endpoint()
def delete_exam():
    """Deletes a manually inserted exam"""

    return exams_service.delete_exam(
        request_data=ExamDeleteRequest(**request.get_json())
    )


@app_exams.route("/exams/types/list", methods=["GET"])
@api_endpoint()
def list_exam_types():
    """Lists all exam types"""

    return exams_service.list_exam_types()
