"""Service for admin reports."""

from datetime import datetime

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import Report
from models.enums import ReportStatusEnum, ReportTypeEnum
from models.main import User, db
from models.requests.admin.admin_report_request import UpsertReportRequest
from repository.reports import reports_repository
from utils import dateutils, sqlutils, status


@has_permission(Permission.WRITE_CUSTOM_REPORTS)
def upsert_report(request_data: UpsertReportRequest, user_context: User):
    """Create or update a report."""

    # Validate SQL query to prevent destructive operations and unauthorized schema access
    sqlutils.validate_sql_query(request_data.sql)
    sqlutils.validate_schema_access(
        sql=request_data.sql, user_schema=user_context.schema
    )

    # Check if it's an update (id provided) or create (no id)
    if request_data.id:
        # Update existing report
        report = reports_repository.get_report(id_report=request_data.id)

        if not report:
            raise ValidationError(
                "Relatório não encontrado",
                "errors.invalidRecord",
                status.HTTP_400_BAD_REQUEST,
            )

        # Update fields
        report.name = request_data.name
        report.description = request_data.description
        report.report_type = ReportTypeEnum.CUSTOM.value
        report.sql = request_data.sql
        report.active = request_data.active
        report.updated_at = datetime.now()
        report.updated_by = user_context.id

        # Reset processing status if SQL changed
        report.status = ReportStatusEnum.NOT_PROCESSED.value
        report.processed_at = None
        report.error = None

    else:
        # Create new report
        report = Report()
        report.name = request_data.name
        report.description = request_data.description
        report.report_type = ReportTypeEnum.CUSTOM.value
        report.sql = request_data.sql
        report.active = request_data.active
        report.status = ReportStatusEnum.NOT_PROCESSED.value
        report.created_at = datetime.now()
        report.created_by = user_context.id

        db.session.add(report)

    db.session.flush()

    return {
        "id": report.id,
        "name": report.name,
        "description": report.description,
        "active": report.active,
        "status": report.status,
    }


@has_permission(Permission.READ_CUSTOM_REPORTS)
def get_report_list(user_context: User):
    """Get list of custom reports."""
    custom_reports_query_result = reports_repository.get_custom_reports(all=True)
    custom_reports = []
    for report in custom_reports_query_result:
        custom_reports.append(
            {
                "id": report.id,
                "name": report.name,
                "description": report.description,
                "active": report.active,
                "status": report.status,
                "updated_at": dateutils.to_iso(report.updated_at),
                "created_at": dateutils.to_iso(report.created_at),
                "error_message": report.error,
                "sql": report.sql,
            }
        )

    return {
        "custom_reports": custom_reports,
        "saved_queries": reports_repository.get_saved_queries(
            schema=user_context.schema
        ),
    }
