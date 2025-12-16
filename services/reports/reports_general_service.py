"""Service: get internal reports"""

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.enums import MemoryEnum, ReportEnum
from models.main import User, db
from services import memory_service
from services.reports import reports_cache_service, reports_custom_service
from utils import status, stringutils


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
        resource_path=_get_resource_path(
            report=report, schema=user_context.schema, filename=filename
        )
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


@has_permission(Permission.READ_REPORTS)
def get_report_list(
    user_context: User,
    user_permissions: list[Permission],
):
    """Get reports configuration. Consider ignored reports from user configuration."""
    user = db.session.query(User).filter(User.id == user_context.id).first()
    ignored_reports = (
        user.reports_config.get("ignore", []) if user.reports_config else []
    )

    external = memory_service.get_memory(MemoryEnum.REPORTS.value)
    internal = memory_service.get_memory(MemoryEnum.REPORTS_INTERNAL.value)

    internal_reports = filter(
        lambda i: i not in ignored_reports, (internal.value if internal else [])
    )
    external_reports = filter(
        lambda i: i.get("title") not in ignored_reports,
        (external.value if external else []),
    )

    if "CUSTOM" in ignored_reports:
        external_reports = []

    return {
        "external": list(external_reports),
        "internal": list(internal_reports),
        "custom": reports_custom_service.get_report_list(),
    }


def _get_resource_path(report, schema, filename="current"):
    """Get resource path for report."""
    resource_path = f"reports/{schema}/{report}/{filename}.gz"
    if not stringutils.is_valid_filename(
        resource_path=resource_path, valid_extensions={".gz"}
    ):
        raise ValidationError(
            "Nome de arquivo inválido",
            "errors.invalidFilename",
            status.HTTP_400_BAD_REQUEST,
        )

    return resource_path
