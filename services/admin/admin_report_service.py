"""Service for admin reports."""

import re
from datetime import datetime

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import Report
from models.enums import ReportStatusEnum, ReportTypeEnum
from models.main import User, db
from models.requests.admin.admin_report_request import UpsertReportRequest
from repository.reports import reports_repository
from utils import dateutils, status


@has_permission(Permission.ADMIN_REPORTS)
def upsert_report(request_data: UpsertReportRequest, user_context: User):
    """Create or update a report."""

    # Validate SQL query to prevent destructive operations
    _validate_sql_query(request_data.sql)

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


@has_permission(Permission.ADMIN_REPORTS)
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


def _validate_sql_query(sql: str):
    """
    Validate SQL query to prevent destructive operations.
    Only SELECT queries are allowed.
    """
    if not sql or not sql.strip():
        raise ValidationError(
            "Query SQL não pode estar vazia",
            "errors.invalidSQL",
            status.HTTP_400_BAD_REQUEST,
        )

    # Remove comments and normalize whitespace
    sql_clean = re.sub(r"--[^\n]*", "", sql)  # Remove single-line comments
    sql_clean = re.sub(
        r"/\*.*?\*/", "", sql_clean, flags=re.DOTALL
    )  # Remove multi-line comments
    sql_clean = sql_clean.lower().strip()

    # List of forbidden SQL keywords/operations
    forbidden_keywords = [
        r"\bdelete\b",
        r"\bdrop\b",
        r"\btruncate\b",
        r"\binsert\b",
        r"\bupdate\b",
        r"\balter\b",
        r"\bcreate\b",
        r"\breplace\b",
        r"\bmerge\b",
        r"\bgrant\b",
        r"\brevoke\b",
        r"\bexec\b",
        r"\bexecute\b",
        r"\bcall\b",
        r"\binto\s+outfile\b",
        r"\bload\s+data\b",
        r"\bload_file\b",
        r"\bcopy\b",
        r"\bimport\b",
        r"\bset\s+"
        r"\bdeclare\b",
        r"\bprepare\b",
        r"\bshutdown\b",
        r"\bkill\b",
    ]

    # Check for forbidden keywords
    for keyword_pattern in forbidden_keywords:
        if re.search(keyword_pattern, sql_clean):
            raise ValidationError(
                "Query SQL contém operação não permitida. Apenas SELECT é permitido.",
                "errors.invalidSQL",
                status.HTTP_400_BAD_REQUEST,
            )

    # Ensure query starts with SELECT or WITH
    if not re.match(r"^\s*(select|with)\b", sql_clean):
        raise ValidationError(
            "Query SQL deve começar com SELECT",
            "errors.invalidSQL",
            status.HTTP_400_BAD_REQUEST,
        )

    # Check for semicolons (potential SQL injection with multiple statements)
    if ";" in sql_clean.rstrip(";"):  # Allow trailing semicolon
        raise ValidationError(
            "Query SQL não pode conter múltiplos comandos (;)",
            "errors.invalidSQL",
            status.HTTP_400_BAD_REQUEST,
        )

    return True
