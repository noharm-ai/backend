"""Service for admin reports."""

from datetime import datetime

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.main import User, db
from models.requests.admin.admin_report_request import UpdateReportGraphsRequest
from repository.reports import reports_repository
from utils import status


@has_permission(Permission.WRITE_CUSTOM_REPORTS_GRAPHS)
def update_report_graphs(
    id_report: int, request_data: UpdateReportGraphsRequest, user_context: User
):
    """Update only the graphs field of a report."""
    report = reports_repository.get_report(id_report=id_report)

    if not report:
        raise ValidationError(
            "Relatório não encontrado",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    report.graphs = request_data.graphs
    report.updated_at = datetime.now()
    report.updated_by = user_context.id

    db.session.flush()

    return {"id": report.id, "graphs": report.graphs}
