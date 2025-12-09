"""Service for generating reports related to regulation."""

from decorators.has_permission_decorator import Permission, has_permission
from models.main import User
from models.requests.regulation_reports_request import RegIndicatorsPanelReportRequest
from repository.reports import reports_regulation_repository
from utils import dateutils


@has_permission(Permission.READ_REPORTS)
def get_indicators_panel_report(request_data: RegIndicatorsPanelReportRequest) -> dict:
    query_result = reports_regulation_repository.get_indicators_panel_report(
        request_data
    )

    results = []

    for row in query_result:
        results.append(
            {
                "id": row.RegIndicatorsPanelReport.id,
                "id_citizen": row.RegIndicatorsPanelReport.id_citizen,
                "admission_number": row.RegIndicatorsPanelReport.admission_number,
                "name": row.RegIndicatorsPanelReport.name,
                "birthdate": row.RegIndicatorsPanelReport.birthdate.isoformat()
                if row.RegIndicatorsPanelReport.birthdate
                else None,
                "age": row.RegIndicatorsPanelReport.age,
                "address": row.RegIndicatorsPanelReport.address,
                "gender": row.RegIndicatorsPanelReport.gender,
                "gestational_age": row.RegIndicatorsPanelReport.gestational_age,
                "cpf": row.RegIndicatorsPanelReport.cpf,
                "cns": row.RegIndicatorsPanelReport.cns,
                "health_unit": row.RegIndicatorsPanelReport.health_unit,
                "health_agent": row.RegIndicatorsPanelReport.health_agent,
                "responsible_team": row.RegIndicatorsPanelReport.responsible_team,
                "ciap": row.RegIndicatorsPanelReport.ciap,
                "icd": row.RegIndicatorsPanelReport.icd,
                "mammogram_appointment_date": row.RegIndicatorsPanelReport.mammogram_appointment_date.isoformat()
                if row.RegIndicatorsPanelReport.mammogram_appointment_date
                else None,
                "hpv_appointment_date": row.RegIndicatorsPanelReport.hpv_appointment_date.isoformat()
                if row.RegIndicatorsPanelReport.hpv_appointment_date
                else None,
                "gestational_appointment_date": row.RegIndicatorsPanelReport.gestational_appointment_date.isoformat()
                if row.RegIndicatorsPanelReport.gestational_appointment_date
                else None,
                "sexattention_appointment_date": row.RegIndicatorsPanelReport.sexattention_appointment_date.isoformat()
                if row.RegIndicatorsPanelReport.sexattention_appointment_date
                else None,
                "hpv_vaccine_date": dateutils.to_iso(
                    row.RegIndicatorsPanelReport.hpv_vaccine_date
                ),
                "has_mammogram": row.RegIndicatorsPanelReport.has_mammogram,
                "has_hpv": row.RegIndicatorsPanelReport.has_hpv,
                "has_vaccine": row.RegIndicatorsPanelReport.has_vaccine,
                "has_sexattention_appointment": row.RegIndicatorsPanelReport.has_sexattention_appointment,
                "has_gestational_appointment": row.RegIndicatorsPanelReport.has_gestational_appointment,
            }
        )

    return {
        "count": query_result[0].total if query_result else 0,
        "data": results,
    }


@has_permission(Permission.READ_REPORTS)
def get_indicators_summary(user_context: User) -> dict:
    """Gets an overview of indicators for the user's schema."""

    return reports_regulation_repository.get_indicators_summary(
        schema=user_context.schema
    )
