"""Service: get custom reports"""

import json
from datetime import datetime, timedelta
from typing import Union

import boto3

from config import Config
from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import Report
from models.enums import ReportStatusEnum
from models.main import User
from repository.reports import reports_repository
from services.reports import reports_cache_service
from utils import dateutils, status, stringutils


@has_permission(Permission.READ_REPORTS)
def get_report_list(user_context: User, user_permissions: list[Permission]):
    """Get list of custom reports."""
    custom_reports_query_result = reports_repository.get_custom_reports(
        all=Permission.READ_CUSTOM_REPORTS in user_permissions
    )
    custom_reports = []
    for report in custom_reports_query_result:
        custom_reports.append(
            {
                "id": report.id,
                "name": report.name,
                "description": report.description,
                "active": report.active,
                "status": report.status,
                "processed_at": dateutils.to_iso(report.processed_at),
                "available_reports": reports_cache_service.list_available_custom_reports(
                    schema=user_context.schema, id_report=report.id
                ),
                "error_message": report.error
                if Permission.READ_CUSTOM_REPORTS in user_permissions
                else None,
            }
        )

    return custom_reports


@has_permission(Permission.READ_REPORTS)
def get_report_link(
    id_report: int,
    user_context: User,
    user_permissions: list[Permission],
    filename: Union[str, None] = None,
):
    """Get custom report presigned link."""
    report_data = reports_repository.get_report(id_report=id_report)

    _validate_report(
        report_data=report_data,
        user_context=user_context,
        user_permissions=user_permissions,
    )

    if filename is None:
        filename = f"{datetime.now().strftime('%Y%m%d')}.csv.gz"

    cached_link = reports_cache_service.generate_link(
        resource_path=_get_resource_path(
            id_report=id_report, schema=user_context.schema, filename=filename
        )
    )

    if not cached_link:
        return {"cached": False}

    return {
        "cached": True,
        "title": report_data.name,
        "url": cached_link,
    }


@has_permission(Permission.READ_REPORTS)
def process_report(
    id_report: int, user_context: User, user_permissions: list[Permission]
):
    """Get custom report presigned link."""
    report_data = reports_repository.get_report(id_report=id_report)

    _validate_report(
        report_data=report_data,
        user_context=user_context,
        user_permissions=user_permissions,
    )

    if report_data.status == ReportStatusEnum.PROCESSING.value:
        raise ValidationError(
            "Relatório já está sendo processado",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    if (
        report_data.processed_at is not None
        and Permission.READ_CUSTOM_REPORTS not in user_permissions
    ):
        # Allow reprocessing only if processed_at is older than 1 hour
        time_since_processed = datetime.now() - report_data.processed_at
        if time_since_processed < timedelta(hours=1):
            raise ValidationError(
                "Relatório já foi processado recentemente. Aguarde 1 hora para processar novamente.",
                "errors.invalidRecord",
                status.HTTP_400_BAD_REQUEST,
            )

    payload = {
        "command": "lambda_custom_reports.process_custom_report",
        "id_user": user_context.id,
        "id_report": id_report,
        "schema": user_context.schema,
    }

    lambda_client = boto3.client("lambda", region_name=Config.NIFI_SQS_QUEUE_REGION)
    lambda_client.invoke(
        FunctionName=Config.BACKEND_FUNCTION_NAME,
        InvocationType="Event",
        Payload=json.dumps(payload),
    )

    # change report status
    report_data.status = ReportStatusEnum.PROCESSING.value

    return True


def _validate_report(
    report_data: Union[Report, None],
    user_context: User,
    user_permissions: list[Permission],
):
    """Check if the report is viewable."""
    if not report_data:
        raise ValidationError(
            "Relatório inválido",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    if Permission.WRITE_CUSTOM_REPORTS in user_permissions:
        return True

    if report_data.active is False:
        raise ValidationError(
            "Relatório não está ativo",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    # user_context is already a User object, no need to query again
    ignored_reports = (
        user_context.reports_config.get("ignore", [])
        if user_context.reports_config
        else []
    )

    if "CUSTOM" in ignored_reports:
        raise ValidationError(
            "Usuário não possui permissão neste recurso",
            "errors.invalidPermission",
            status.HTTP_401_UNAUTHORIZED,
        )

    return True


def _get_resource_path(id_report: int, schema: str, filename: str):
    """Get resource path for custom report."""

    resource_path = f"reports/{schema}/CUSTOM/{id_report}/{filename}"

    if not stringutils.is_valid_filename(
        resource_path=resource_path, valid_extensions={".csv", ".xlsx", ".json.gz"}
    ):
        raise ValidationError(
            "Nome de arquivo inválido",
            "errors.invalidFilename",
            status.HTTP_400_BAD_REQUEST,
        )

    return resource_path
