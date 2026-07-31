from flask import Blueprint, request
from markupsafe import escape as escape_html

from decorators.api_endpoint_decorator import api_endpoint
from services.admin import admin_segment_service

app_admin_segment = Blueprint("app_admin_segment", __name__)


@app_admin_segment.route(
    "/admin/segments/departments/<int:id_segment>", methods=["GET"]
)
@api_endpoint(is_admin=True)
def get_departments(id_segment):
    return admin_segment_service.get_departments(id_segment)


@app_admin_segment.route("/admin/segments/departments", methods=["POST"])
@api_endpoint(is_admin=True)
def upsert_department():
    data = request.get_json()

    admin_segment_service.update_segment_departments(
        id_segment=data.get("idSegment", None),
        department_list=data.get("departmentList", None),
    )

    return escape_html(data.get("idSegment"))
