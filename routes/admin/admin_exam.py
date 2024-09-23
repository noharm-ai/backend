from flask import Blueprint, request

from decorators.api_endpoint_decorator import (
    api_endpoint,
    ApiEndpointUserGroup,
    ApiEndpointAction,
)
from models.main import User
from services.admin import admin_exam_service

app_admin_exam = Blueprint("app_admin_exam", __name__)


@app_admin_exam.route("/admin/exam/copy", methods=["POST"])
@api_endpoint(
    user_group=ApiEndpointUserGroup.MAINTAINER, action=ApiEndpointAction.WRITE
)
def copy_exams(user_context: User):
    data = request.get_json()

    result = admin_exam_service.copy_exams(
        id_segment_origin=data.get("idSegmentOrigin", None),
        id_segment_destiny=data.get("idSegmentDestiny", None),
        user=user_context,
    )

    return result.rowcount


@app_admin_exam.route("/admin/exam/most-frequent", methods=["GET"])
@api_endpoint(user_group=ApiEndpointUserGroup.MAINTAINER, action=ApiEndpointAction.READ)
def get_most_frequent(user_context: User):
    return admin_exam_service.get_most_frequent(user=user_context)


@app_admin_exam.route("/admin/exam/list", methods=["POST"])
@api_endpoint(user_group=ApiEndpointUserGroup.ALL, action=ApiEndpointAction.READ)
def list_exams(user_context: User):
    data = request.get_json()

    return admin_exam_service.get_segment_exams(
        user=user_context, id_segment=data.get("idSegment", None)
    )


@app_admin_exam.route("/admin/exam/types", methods=["GET"])
@api_endpoint(user_group=ApiEndpointUserGroup.ALL, action=ApiEndpointAction.READ)
def list_exam_types():
    return admin_exam_service.get_exam_types()


@app_admin_exam.route("/admin/exam/most-frequent/add", methods=["POST"])
@api_endpoint(
    user_group=ApiEndpointUserGroup.MAINTAINER, action=ApiEndpointAction.WRITE
)
def add_most_frequent(user_context: User):
    data = request.get_json()

    admin_exam_service.add_most_frequent(
        id_segment=data.get("idSegment", None),
        exam_types=data.get("examTypes", None),
        user=user_context,
    )

    return True


@app_admin_exam.route("/admin/exam/upsert", methods=["POST"])
@api_endpoint(user_group=ApiEndpointUserGroup.ALL, action=ApiEndpointAction.WRITE)
def upsert_seg_exam(user_context: User):
    data = request.get_json()

    return admin_exam_service.upsert_seg_exam(data=data, user=user_context)


@app_admin_exam.route("/admin/exam/order", methods=["POST"])
@api_endpoint(user_group=ApiEndpointUserGroup.ALL, action=ApiEndpointAction.WRITE)
def set_exams_order(user_context: User):
    data = request.get_json()

    return admin_exam_service.set_exams_order(
        exams=data.get("exams", None),
        id_segment=data.get("idSegment", None),
        user=user_context,
    )
