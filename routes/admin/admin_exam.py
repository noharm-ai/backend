from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services.admin import admin_exam_service

app_admin_exam = Blueprint("app_admin_exam", __name__)


@app_admin_exam.route("/admin/exam/copy", methods=["POST"])
@api_endpoint(is_admin=True)
def copy_exams():
    data = request.get_json()

    result = admin_exam_service.copy_exams(
        id_segment_origin=data.get("idSegmentOrigin", None),
        id_segment_destiny=data.get("idSegmentDestiny", None),
    )

    return result.rowcount


@app_admin_exam.route("/admin/exam/most-frequent", methods=["GET"])
@api_endpoint(is_admin=True)
def get_most_frequent():
    return admin_exam_service.get_most_frequent()


@app_admin_exam.route("/admin/exam/list", methods=["POST"])
@api_endpoint()
def list_exams():
    data = request.get_json()

    return admin_exam_service.get_segment_exams(id_segment=data.get("idSegment", None))


@app_admin_exam.route("/admin/exam/types", methods=["GET"])
@api_endpoint()
def list_exam_types():
    return admin_exam_service.get_exam_types()


@app_admin_exam.route("/admin/exam/list-global", methods=["GET"])
@api_endpoint()
def list_global_exams():
    return admin_exam_service.get_global_exams()


@app_admin_exam.route("/admin/exam/most-frequent/add", methods=["POST"])
@api_endpoint(is_admin=True)
def add_most_frequent():
    data = request.get_json()

    admin_exam_service.add_most_frequent(
        id_segment=data.get("idSegment", None),
        exam_types=data.get("examTypes", None),
    )

    return True


@app_admin_exam.route("/admin/exam/upsert", methods=["POST"])
@api_endpoint()
def upsert_seg_exam():
    data = request.get_json()

    return admin_exam_service.upsert_seg_exam(data=data)


@app_admin_exam.route("/admin/exam/order", methods=["POST"])
@api_endpoint()
def set_exams_order():
    data = request.get_json()

    return admin_exam_service.set_exams_order(
        exams=data.get("exams", None),
        id_segment=data.get("idSegment", None),
    )
