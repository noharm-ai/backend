from models.main import *
from models.appendix import *
from models.segment import *
from models.enums import ReportEnum
from services.reports import cache_service
from exception.validation_error import ValidationError


def get_report(user, report, filename="current"):
    available_reports = list(map(lambda c: c.value, ReportEnum))
    if report not in available_reports:
        raise ValidationError(
            "Relatório inválido",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    cached_link = cache_service.generate_link(
        report=report, schema=user.schema, filename=filename
    )

    if cached_link == None:
        return {"cached": False}

    return {
        "cached": True,
        "url": cache_service.generate_link(report, user.schema),
    }
