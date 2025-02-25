"""Service: get internal reports"""

from models.enums import ReportEnum
from models.main import db, User
from services.reports import reports_cache_service
from utils import status
from exception.validation_error import ValidationError
from decorators.has_permission_decorator import has_permission, Permission


@has_permission(Permission.READ_REPORTS)
def get_report(report, user_context: User, filename="current"):
    """Get report and list available history reports."""
    user = db.session.query(User).filter(User.id == user_context.id).first()
    ignored_reports = (
        user.reports_config.get("ignore", []) if user.reports_config else []
    )
    available_reports = list(map(lambda c: c.value, ReportEnum))
    if report not in available_reports:
        raise ValidationError(
            "Relatório inválido",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    if report in ignored_reports:
        raise ValidationError(
            "Usuário não possui permissão neste recurso",
            "errors.invalidPermission",
            status.HTTP_401_UNAUTHORIZED,
        )

    cached_link = reports_cache_service.generate_link(
        report=report, schema=user_context.schema, filename=filename
    )

    if not cached_link:
        return {"cached": False}

    return {
        "cached": True,
        "availableReports": reports_cache_service.list_available_reports(
            schema=user_context.schema, report=report
        ),
        "url": cached_link,
    }
