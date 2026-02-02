"""Route: admin global exam related endpoints"""

from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from models.requests.admin.admin_global_exam import (
    GlobalExamListRequest,
    GlobalExamUpsertRequest,
)
from services.admin import admin_global_exam_service

app_admin_global_exam = Blueprint("app_admin_global_exam", __name__)


@app_admin_global_exam.route("/admin/global-exam/list", methods=["POST"])
@api_endpoint(is_admin=True)
def list_global_exams():
    """List all and filter global exams"""
    return admin_global_exam_service.list_global_exams(
        request_data=GlobalExamListRequest(**request.get_json())
    )


@app_admin_global_exam.route("/admin/global-exam/upsert", methods=["POST"])
@api_endpoint(is_admin=True)
def upsert():
    """Upsert global exam"""
    return admin_global_exam_service.upsert_global_exam(
        request_data=GlobalExamUpsertRequest(**request.get_json())
    )
