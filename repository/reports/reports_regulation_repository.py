"""Repository for generating reports related to regulation."""

from sqlalchemy import asc, desc, func, nullslast, text

from models.enums import RegulationIndicatorReportEnum
from models.main import db
from models.regulation import RegIndicatorsPanelReport
from models.requests.regulation_reports_request import RegIndicatorsPanelReportRequest
from utils import numberutils


def get_indicators_panel_report(request_data: RegIndicatorsPanelReportRequest):
    query = db.session.query(
        RegIndicatorsPanelReport,
        func.count().over().label("total"),
    )

    if request_data.indicator == RegulationIndicatorReportEnum.HPV_VACCINE.value:
        query = query.filter(RegIndicatorsPanelReport.has_vaccine != None)

        if request_data.has_indicator is not None:
            query = query.filter(
                RegIndicatorsPanelReport.has_vaccine == request_data.has_indicator
            )

    if request_data.indicator == RegulationIndicatorReportEnum.HPV_EXAM.value:
        query = query.filter(RegIndicatorsPanelReport.has_hpv != None)

        if request_data.has_indicator is not None:
            query = query.filter(
                RegIndicatorsPanelReport.has_hpv == request_data.has_indicator
            )

    if (
        request_data.indicator
        == RegulationIndicatorReportEnum.SEXUAL_ATTENTION_APPOINTMENT.value
    ):
        query = query.filter(
            RegIndicatorsPanelReport.has_sexattention_appointment != None
        )

        if request_data.has_indicator is not None:
            query = query.filter(
                RegIndicatorsPanelReport.has_sexattention_appointment
                == request_data.has_indicator
            )

    if request_data.indicator == RegulationIndicatorReportEnum.MAMMOGRAM_EXAM.value:
        query = query.filter(RegIndicatorsPanelReport.has_mammogram != None)

        if request_data.has_indicator is not None:
            query = query.filter(
                RegIndicatorsPanelReport.has_mammogram == request_data.has_indicator
            )

    if (
        request_data.indicator
        == RegulationIndicatorReportEnum.GESTATIONAL_APPOINTMENT.value
    ):
        query = query.filter(
            RegIndicatorsPanelReport.has_gestational_appointment != None
        )

        if request_data.has_indicator is not None:
            query = query.filter(
                RegIndicatorsPanelReport.has_gestational_appointment
                == request_data.has_indicator
            )

    if request_data.name is not None:
        query = query.filter(
            RegIndicatorsPanelReport.name.ilike(f"%{request_data.name}%")
        )

    if request_data.cpf is not None:
        query = query.filter(RegIndicatorsPanelReport.cpf == request_data.cpf)

    if request_data.cns is not None:
        query = query.filter(RegIndicatorsPanelReport.cns == request_data.cns)

    if request_data.age_min is not None:
        query = query.filter(RegIndicatorsPanelReport.age >= request_data.age_min)

    if request_data.age_max is not None:
        query = query.filter(RegIndicatorsPanelReport.age <= request_data.age_max)

    if request_data.gender is not None:
        query = query.filter(RegIndicatorsPanelReport.gender == request_data.gender)

    if request_data.health_unit is not None:
        query = query.filter(
            RegIndicatorsPanelReport.health_unit.ilike(f"%{request_data.health_unit}%")
        )

    if request_data.health_team is not None:
        query = query.filter(
            RegIndicatorsPanelReport.responsible_team.ilike(
                f"%{request_data.health_team}%"
            )
        )

    if request_data.health_agent is not None:
        query = query.filter(
            RegIndicatorsPanelReport.health_agent.ilike(
                f"%{request_data.health_agent}%"
            )
        )

    for order in request_data.order:
        direction = desc if order.direction == "desc" else asc
        if order.field in ["name"]:
            query = query.order_by(
                nullslast(direction(getattr(RegIndicatorsPanelReport, order.field)))
            )

        if order.field in ["birthdate"]:
            direction = asc if order.direction == "desc" else desc
            query = query.order_by(
                nullslast(direction(getattr(RegIndicatorsPanelReport, order.field)))
            )

    query = query.limit(request_data.limit).offset(request_data.offset)

    return query.all()


def get_indicators_summary(schema: str) -> dict:
    config = [
        {
            "indicator": RegulationIndicatorReportEnum.MAMMOGRAM_EXAM.value,
            "field": "fez_mamografia",
            "weight": 20,
        },
        {
            "indicator": RegulationIndicatorReportEnum.HPV_EXAM.value,
            "field": "fez_hpv",
            "weight": 20,
        },
        {
            "indicator": RegulationIndicatorReportEnum.HPV_VACCINE.value,
            "field": "fez_vacina",
            "weight": 30,
        },
        {
            "indicator": RegulationIndicatorReportEnum.SEXUAL_ATTENTION_APPOINTMENT.value,
            "field": "fez_consulta_sex",
            "weight": 30,
        },
        {
            "indicator": RegulationIndicatorReportEnum.GESTATIONAL_APPOINTMENT.value,
            "field": "fez_consulta_gest",
            "weight": 9,
        },
    ]

    mainquery_fields = []
    subquery_fields = []
    for ind in config:
        subquery_fields.append(
            f"case when {ind['field']} is not null then 1 else 0 end as {ind['indicator']}"
        )
        subquery_fields.append(
            f"case when {ind['field']} = true then 1 else 0 end as {ind['field']}"
        )

        mainquery_fields.append(
            f"cast(sum({ind['field']}) as decimal) / nullif(sum({ind['indicator']}), 0) * {ind['weight']} as {ind['indicator']}"
        )

    query = f"""
        select
            {", ".join(mainquery_fields)}
        from (
            select
                {", ".join(subquery_fields)}
            from
                {schema}.rel_painel_juntos
        ) as subquery
    """

    query_result = db.session.execute(text(query)).first()

    if query_result is None:
        return {}

    indicators = {}
    for ind in config:
        indicators[ind["indicator"]] = {
            "value": round(
                numberutils.none2zero(getattr(query_result, ind["indicator"].lower())),
                2,
            ),
            "weight": ind["weight"],
        }

    return indicators
