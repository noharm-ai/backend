import json

import boto3

from config import Config
from decorators.has_permission_decorator import Permission, has_permission
from models.enums import NoHarmENV
from models.main import User
from models.requests.reports_consolidated_request import PatientDayReportRequest


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
    }

    lambda_client = boto3.client("lambda", region_name=Config.NIFI_SQS_QUEUE_REGION)
    response = lambda_client.invoke(
        FunctionName=Config.BACKEND_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload),
    )

    return json.loads(response["Payload"].read().decode("utf-8"))
