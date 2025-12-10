"""Route definitions for the regulation reports."""

from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from models.requests.regulation_reports_request import RegIndicatorsPanelReportRequest
from services.reports import reports_regulation_service

app_rpt_regulation = Blueprint("app_rpt_regulation", __name__)


@app_rpt_regulation.route("/reports/regulation/indicators-panel", methods=["POST"])
@api_endpoint()
def get_indicators_panel():
    """Gets indicator panel report data"""
    return reports_regulation_service.get_indicators_panel_report(
        request_data=RegIndicatorsPanelReportRequest(**request.get_json())
    )


@app_rpt_regulation.route("/reports/regulation/indicators-panel-csv", methods=["POST"])
@api_endpoint(
    download_headers={
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": "attachment; filename=indicadores.csv",
    }
)
def get_indicators_panel_csv():
    """Gets indicator panel report data as CSV"""
    return reports_regulation_service.get_indicators_panel_report_csv(
        request_data=RegIndicatorsPanelReportRequest(**request.get_json())
    )


@app_rpt_regulation.route("/reports/regulation/indicators-summary", methods=["GET"])
@api_endpoint()
def get_indicators_summary():
    """Gets an overview of all indicators"""
    return reports_regulation_service.get_indicators_summary()
