"""Exams routes module"""

from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from models.requests.exam_request import (
    ExamCreateMultipleRequest,
    ExamCreateRequest,
    ExamDeleteRequest,
)
from services import exams_service

app_exams = Blueprint("app_exams", __name__)


# deprecated
@app_exams.route("/exams/create", methods=["POST"])
@api_endpoint()
def create_exam():
    """Creates a new exam"""

    return exams_service.create_exam(
        request_data=ExamCreateRequest(**request.get_json())
    )


@app_exams.route("/exams/create-multiple", methods=["POST"])
@api_endpoint()
def create_exam_multiple():
    """Creates a new exam (multiple entries)"""

    return exams_service.create_exam_multiple(
        request_data=ExamCreateMultipleRequest(**request.get_json())
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


@app_exams.route("/exams/<int:admission_number>", methods=["GET"])
@api_endpoint()
def get_exams_by_admission(admission_number):
    return exams_service.get_exams_by_admission(
        admission_number=admission_number, id_segment=request.args.get("idSegment", 1)
    )
