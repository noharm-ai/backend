"""Route: Admin Report"""

from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from models.requests.admin.admin_report_request import (
    UpdateReportGraphsRequest,
    UpsertReportRequest,
)
from services.admin import admin_report_service

app_admin_report = Blueprint("app_admin_report", __name__)


@app_admin_report.route("/admin/report", methods=["POST"])
@api_endpoint(is_admin=True)
def upsert_report():
    return admin_report_service.upsert_report(
        request_data=UpsertReportRequest(**request.get_json())
    )


@app_admin_report.route("/admin/report/<int:id_report>/graphs", methods=["PATCH"])
@api_endpoint(is_admin=True)
def update_report_graphs(id_report: int):
    """Update graphs configuration for a report."""
    return admin_report_service.update_report_graphs(
        id_report=id_report,
        request_data=UpdateReportGraphsRequest(**request.get_json()),
    )


@app_admin_report.route("/admin/report/list", methods=["GET"])
@api_endpoint(is_admin=True)
def get_list():
    """List custom reports."""
    return admin_report_service.get_report_list()
