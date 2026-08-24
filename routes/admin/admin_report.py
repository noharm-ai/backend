"""Route: Admin Report"""

from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from models.requests.admin.admin_report_request import (
    CopySourceGraphsRequest,
    CopySourceListRequest,
    UpdateReportGraphsRequest,
)
from services.admin import admin_report_service

app_admin_report = Blueprint("app_admin_report", __name__)


@app_admin_report.route("/admin/report/<int:id_report>/graphs", methods=["PATCH"])
@api_endpoint(is_admin=True)
def update_report_graphs(id_report: int):
    """Update graphs configuration for a report."""
    return admin_report_service.update_report_graphs(
        id_report=id_report,
        request_data=UpdateReportGraphsRequest(**request.get_json()),
    )


@app_admin_report.route("/admin/report/copy-source/list", methods=["GET"])
@api_endpoint(is_admin=True)
def get_copy_source_reports():
    """List the reports whose charts may be copied, optionally from another schema."""
    return admin_report_service.get_copy_source_reports(
        request_data=CopySourceListRequest(
            sourceSchema=request.args.get("sourceSchema", None)
        ),
    )


@app_admin_report.route(
    "/admin/report/copy-source/<int:id_report>/graphs", methods=["GET"]
)
@api_endpoint(is_admin=True)
def get_copy_source_graphs(id_report: int):
    """Get the charts of a copy-source report."""
    return admin_report_service.get_copy_source_graphs(
        request_data=CopySourceGraphsRequest(
            idReport=id_report,
            sourceSchema=request.args.get("sourceSchema", None),
        ),
    )
