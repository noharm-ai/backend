import json

from config import Config
from decorators.has_permission_decorator import Permission, has_permission
from models.enums import NoHarmENV
from models.main import User
from models.requests.reports_consolidated_request import (
    EconomyReportRequest,
    InterventionReportRequest,
    PatientDayReportRequest,
    PrescriptionReportRequest,
)
from utils import aws


def _invoke_report_lambda(payload: dict, report_name: str) -> dict:
    """Invoke the private backend lambda and return the parsed report payload."""
    lambda_client = aws.get_client("lambda", region_name=Config.NIFI_SQS_QUEUE_REGION)
    response = lambda_client.invoke(
        FunctionName=Config.BACKEND_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload),
    )

    response_json = json.loads(response["Payload"].read().decode("utf-8"))

    if isinstance(response_json, str):
        response_json = json.loads(response_json)

    if response_json.get("error", False):
        raise Exception(
            f"Consolidated {report_name} report ERROR: {response_json.get('message', 'Erro inesperado. Consulte os logs')}"
        )

    return response_json


@has_permission(Permission.READ_REPORTS)
def get_patient_day_report(request_data: PatientDayReportRequest, user_context: User):
    if Config.ENV == NoHarmENV.TEST.value:
        return {}

    payload = {
        "command": "lambda_query_reports.get_patient_day_report",
        "schema": user_context.schema,
        "year": request_data.year,
        "id_department": request_data.id_department
        if request_data.id_department
        else None,
        "segment": request_data.segment if request_data.segment else None,
        "start_date": (
            request_data.start_date.isoformat() if request_data.start_date else None
        ),
        "end_date": (
            request_data.end_date.isoformat() if request_data.end_date else None
        ),
        "global_score_start": request_data.global_score_start,
        "global_score_end": request_data.global_score_end,
        "weekdays_only": request_data.weekdays_only,
    }

    return _invoke_report_lambda(payload=payload, report_name="patient-day")


@has_permission(Permission.READ_REPORTS)
def get_prescription_report(request_data: PrescriptionReportRequest, user_context: User):
    if Config.ENV == NoHarmENV.TEST.value:
        return {}

    payload = {
        "command": "lambda_query_reports.get_prescription_report",
        "schema": user_context.schema,
        "year": request_data.year,
        "id_department": request_data.id_department if request_data.id_department else None,
        "segment": request_data.segment if request_data.segment else None,
        "start_date": (
            request_data.start_date.isoformat() if request_data.start_date else None
        ),
        "end_date": (
            request_data.end_date.isoformat() if request_data.end_date else None
        ),
        "global_score_start": request_data.global_score_start,
        "global_score_end": request_data.global_score_end,
        "weekdays_only": request_data.weekdays_only,
        "consider_empty_prescriptions": request_data.consider_empty_prescriptions,
        "remove_prescription_at_discharge_date": request_data.remove_prescription_at_discharge_date,
    }

    return _invoke_report_lambda(payload=payload, report_name="prescription")


@has_permission(Permission.READ_REPORTS)
def get_economy_report(request_data: EconomyReportRequest, user_context: User):
    if Config.ENV == NoHarmENV.TEST.value:
        return {}

    payload = {
        "command": "lambda_query_reports.get_economy_report",
        "schema": user_context.schema,
        "year": request_data.year,
        "department": request_data.department if request_data.department else None,
        "segment": request_data.segment if request_data.segment else None,
        "start_date": (
            request_data.start_date.isoformat() if request_data.start_date else None
        ),
        "end_date": (
            request_data.end_date.isoformat() if request_data.end_date else None
        ),
        "economy_type": request_data.economy_type if request_data.economy_type else None,
        "status": request_data.status if request_data.status else None,
        "responsible": request_data.responsible if request_data.responsible else None,
        "economy_value_type": request_data.economy_value_type
        if request_data.economy_value_type
        else None,
    }

    return _invoke_report_lambda(payload=payload, report_name="economy")


@has_permission(Permission.READ_REPORTS)
def get_intervention_report(
    request_data: InterventionReportRequest, user_context: User
):
    if Config.ENV == NoHarmENV.TEST.value:
        return {}

    payload = {
        "command": "lambda_query_reports.get_intervention_report",
        "schema": user_context.schema,
        "year": request_data.year,
        "department": request_data.department if request_data.department else None,
        "segment": request_data.segment if request_data.segment else None,
        "start_date": (
            request_data.start_date.isoformat() if request_data.start_date else None
        ),
        "end_date": (
            request_data.end_date.isoformat() if request_data.end_date else None
        ),
        "status": request_data.status if request_data.status else None,
        "responsible": request_data.responsible if request_data.responsible else None,
        "prescriber": request_data.prescriber if request_data.prescriber else None,
        "insurance": request_data.insurance if request_data.insurance else None,
        "reason": request_data.reason if request_data.reason else None,
    }

    return _invoke_report_lambda(payload=payload, report_name="intervention")
