"""Route: Admin Report"""

from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from models.requests.admin.admin_report_request import UpsertReportRequest
from services.admin import admin_report_service

app_admin_report = Blueprint("app_admin_report", __name__)


@app_admin_report.route("/admin/report", methods=["POST"])
@api_endpoint(is_admin=True)
def upsert_report():
    return admin_report_service.upsert_report(
        request_data=UpsertReportRequest(**request.get_json())
    )


@app_admin_report.route("/admin/report/list", methods=["GET"])
@api_endpoint(is_admin=True)
def get_list():
    """List custom reports."""
    return admin_report_service.get_report_list()
