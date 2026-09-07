"""Unit tests for the regulation indicators panel report.

The "Painel Juntos" report reads the ``rel_painel_juntos`` view, which holds one
row per citizen record with a boolean per health indicator (mammogram, HPV exam
and vaccine, sexual-health and gestational appointments, …). Three endpoints are
served from it:

* ``/reports/regulation/indicators-panel`` — the paginated table;
* ``/reports/regulation/indicators-panel-csv`` — the same rows as a CSV file;
* ``/reports/regulation/indicators-summary`` — the weighted score per indicator.

The regulation tables live in a separate DDL file that neither CI nor the local
``make test-setup`` loads, so these are unit tests (same approach as
``tests/unit/test_regulation_solicitation.py``): ``db`` is replaced with a
recording double and the repository is patched when testing the service. Real
SQLAlchemy model instances and real query expressions are still used, so the
column mapping and the filters are exercised for real — the filter and ordering
expressions are asserted through their compiled SQL. The ``@has_permission``
gate is bypassed via ``__wrapped__`` except in the tests that assert the gate
itself.
"""

import csv
from contextlib import contextmanager
from datetime import date
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from exception.authorization_error import AuthorizationError
from mobile import app
from models.enums import RegulationIndicatorReportEnum
from models.main import User
from models.regulation import RegIndicatorsPanelReport
from models.requests.regulation_reports_request import RegIndicatorsPanelReportRequest
from repository.reports import reports_regulation_repository
from security.role import Role
from services.reports import reports_regulation_service

# Undecorated business logic (skips the permission gate).
_get_panel = reports_regulation_service.get_indicators_panel_report.__wrapped__
_get_panel_csv = reports_regulation_service.get_indicators_panel_report_csv.__wrapped__
_get_summary = reports_regulation_service.get_indicators_summary.__wrapped__

# masked when the HIDE_NAMES feature is on
_IDENTIFYING_FIELDS = ["name", "address", "gender", "cpf", "cns", "health_agent"]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _request(**overrides):
    """Build a RegIndicatorsPanelReportRequest with sensible defaults."""
    payload = {
        "indicator": RegulationIndicatorReportEnum.HPV_EXAM.value,
        "limit": 50,
        "offset": 0,
        "order": [],
    }
    payload.update(overrides)
    return RegIndicatorsPanelReportRequest(**payload)


def _panel_row(**overrides):
    """Build a fully populated RegIndicatorsPanelReport row."""
    values = {
        "id": 9000000001,
        "id_citizen": "CID-1",
        "admission_number": 90000001,
        "name": "Fulano Beltrano",
        "birthdate": date(1990, 5, 4),
        "age": 36,
        "address": "Rua de Teste, 1",
        "gender": "F",
        "gestational_age": "12s",
        "cpf": "000.000.000-00",
        "cns": "000000000000000",
        "health_unit": "UBS Teste",
        "health_agent": "Ciclano de Tal",
        "responsible_team": "Equipe Teste",
        "ciap": "W78",
        "icd": "Z34",
        "mammogram_appointment_date": date(2026, 1, 5),
        "hpv_appointment_date": date(2026, 2, 6),
        "gestational_appointment_date": date(2026, 3, 7),
        "sexattention_appointment_date": date(2026, 4, 8),
        "seven_gestational_appointments_date": date(2026, 5, 9),
        "hpv_vaccine_date": date(2026, 6, 10),
        "gestational_pressure_measurements_date": date(2026, 7, 11),
        "weight_height_measurements_date": date(2026, 8, 12),
        "has_mammogram": True,
        "has_hpv": False,
        "has_vaccine": True,
        "has_sexattention_appointment": False,
        "has_gestational_appointment": True,
        "has_seven_gestational_appointments": False,
        "has_gestational_pressure_measurements": True,
        "has_weight_height_measurements": False,
    }
    values.update(overrides)

    row = RegIndicatorsPanelReport()
    for field, value in values.items():
        setattr(row, field, value)

    return row


def _repository_row(row=None, total=1):
    """Wrap a model row the way the windowed repository query returns it."""
    return SimpleNamespace(
        RegIndicatorsPanelReport=row if row is not None else _panel_row(),
        total=total,
    )


@contextmanager
def _hide_names(enabled):
    """Force the HIDE_NAMES feature flag on or off for the block."""
    with patch.object(
        reports_regulation_service.feature_service,
        "has_user_feature",
        return_value=enabled,
    ):
        yield


@contextmanager
def _repository(rows):
    """Patch the repository so the service reads ``rows``."""
    with patch.object(
        reports_regulation_service.reports_regulation_repository,
        "get_indicators_panel_report",
        return_value=rows,
    ) as mock_get:
        yield mock_get


@contextmanager
def acting_as(roles):
    """Run the block inside a request context authenticated as ``roles``.

    Patches the permission decorator's JWT identity lookup and ``User`` model
    so the decorated service resolves a fabricated user carrying ``roles``.
    """
    fake_user = MagicMock()
    fake_user.id = 7
    fake_user.schema = "demo"
    fake_user.config = {"roles": roles}
    with app.test_request_context():
        with (
            patch(
                "decorators.has_permission_decorator.get_jwt_identity", return_value=1
            ),
            patch("decorators.has_permission_decorator.User") as mock_user_cls,
        ):
            mock_user_cls.find.return_value = fake_user
            yield


class _QueryRecorder:
    """Stands in for a SQLAlchemy Query, recording what the repository builds."""

    def __init__(self, rows):
        self.rows = list(rows)
        self.filters = []
        self.orders = []
        self.limit_value = None
        self.offset_value = None

    def filter(self, *criteria):
        self.filters.extend(criteria)
        return self

    def order_by(self, *criteria):
        self.orders.extend(criteria)
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def offset(self, value):
        self.offset_value = value
        return self

    def all(self):
        return self.rows


def _sql(expression):
    """Compile a query expression to SQL, inlining the bound values."""
    return str(expression.compile(compile_kwargs={"literal_binds": True}))


def _run_repository_query(request_data, rows=()):
    """Run the repository against a recording session and return the recorder."""
    recorder = _QueryRecorder(rows)
    mock_db = MagicMock()
    mock_db.session.query.return_value = recorder

    with patch.object(reports_regulation_repository, "db", mock_db):
        result = reports_regulation_repository.get_indicators_panel_report(request_data)

    return recorder, result


def _filters_sql(recorder):
    """The compiled SQL of every filter applied to the query."""
    return [_sql(criteria) for criteria in recorder.filters]


# --------------------------------------------------------------------------
# service — get_indicators_panel_report
# --------------------------------------------------------------------------


def test_panel_report_on_an_empty_result():
    """No rows means an empty list and a zero count."""
    with _repository([]), _hide_names(False):
        assert _get_panel(request_data=_request()) == {"count": 0, "data": []}


def test_panel_report_reads_the_count_from_the_window_function():
    """The total comes from the window column of the first row, not from len()."""
    rows = [_repository_row(total=137), _repository_row(total=137)]

    with _repository(rows), _hide_names(False):
        result = _get_panel(request_data=_request())

    assert result["count"] == 137
    assert len(result["data"]) == 2


def test_panel_report_maps_the_full_row():
    """Every column of the view reaches the payload under its API name."""
    with _repository([_repository_row(total=1)]), _hide_names(False):
        record = _get_panel(request_data=_request())["data"][0]

    assert record["id"] == 9000000001
    assert record["id_citizen"] == "CID-1"
    assert record["admission_number"] == 90000001
    assert record["name"] == "Fulano Beltrano"
    assert record["birthdate"] == "1990-05-04"
    assert record["age"] == 36
    assert record["address"] == "Rua de Teste, 1"
    assert record["gender"] == "F"
    assert record["gestational_age"] == "12s"
    assert record["cpf"] == "000.000.000-00"
    assert record["cns"] == "000000000000000"
    assert record["health_unit"] == "UBS Teste"
    assert record["health_agent"] == "Ciclano de Tal"
    assert record["responsible_team"] == "Equipe Teste"
    assert record["ciap"] == "W78"
    assert record["icd"] == "Z34"


def test_panel_report_serializes_every_date_as_iso():
    """Dates are exposed as ISO strings."""
    with _repository([_repository_row(total=1)]), _hide_names(False):
        record = _get_panel(request_data=_request())["data"][0]

    assert record["mammogram_appointment_date"] == "2026-01-05"
    assert record["hpv_appointment_date"] == "2026-02-06"
    assert record["gestational_appointment_date"] == "2026-03-07"
    assert record["sexattention_appointment_date"] == "2026-04-08"
    assert record["seven_gestational_appointments_date"] == "2026-05-09"
    assert record["hpv_vaccine_date"] == "2026-06-10"
    assert record["gestational_pressure_measurements_date"] == "2026-07-11"
    assert record["weight_height_measurements_date"] == "2026-08-12"


def test_panel_report_keeps_the_indicator_booleans_as_they_are():
    """The three-state indicators (true/false/null) are not coerced."""
    row = _panel_row(has_mammogram=True, has_hpv=False, has_vaccine=None)

    with _repository([_repository_row(row=row, total=1)]), _hide_names(False):
        record = _get_panel(request_data=_request())["data"][0]

    assert record["has_mammogram"] is True
    assert record["has_hpv"] is False
    assert record["has_vaccine"] is None
    assert record["has_sexattention_appointment"] is False
    assert record["has_gestational_appointment"] is True
    assert record["has_seven_gestational_appointments"] is False
    assert record["has_gestational_pressure_measurements"] is True
    assert record["has_weight_height_measurements"] is False


def test_panel_report_tolerates_a_row_without_dates():
    """Missing dates come back as null instead of raising."""
    row = _panel_row(
        birthdate=None,
        mammogram_appointment_date=None,
        hpv_appointment_date=None,
        gestational_appointment_date=None,
        sexattention_appointment_date=None,
        seven_gestational_appointments_date=None,
        hpv_vaccine_date=None,
        gestational_pressure_measurements_date=None,
        weight_height_measurements_date=None,
    )

    with _repository([_repository_row(row=row, total=1)]), _hide_names(False):
        record = _get_panel(request_data=_request())["data"][0]

    assert record["birthdate"] is None
    assert record["mammogram_appointment_date"] is None
    assert record["hpv_appointment_date"] is None
    assert record["gestational_appointment_date"] is None
    assert record["sexattention_appointment_date"] is None
    assert record["seven_gestational_appointments_date"] is None
    assert record["hpv_vaccine_date"] is None
    assert record["gestational_pressure_measurements_date"] is None
    assert record["weight_height_measurements_date"] is None


def test_panel_report_masks_the_identifying_fields_when_hide_names_is_on():
    """HIDE_NAMES replaces the citizen's identification with ``***``."""
    with _repository([_repository_row(total=1)]), _hide_names(True):
        record = _get_panel(request_data=_request())["data"][0]

    for field in _IDENTIFYING_FIELDS:
        assert record[field] == "***", field


def test_panel_report_masking_keeps_the_clinical_columns_readable():
    """Only the identifying fields are masked; the indicators stay usable."""
    with _repository([_repository_row(total=1)]), _hide_names(True):
        record = _get_panel(request_data=_request())["data"][0]

    assert record["id"] == 9000000001
    assert record["age"] == 36
    assert record["birthdate"] == "1990-05-04"
    assert record["health_unit"] == "UBS Teste"
    assert record["responsible_team"] == "Equipe Teste"
    assert record["icd"] == "Z34"
    assert record["has_mammogram"] is True


def test_panel_report_forwards_the_request_to_the_repository():
    """The request object reaches the repository untouched."""
    request_data = _request(name="Fulano", limit=10, offset=20)

    with _repository([]) as mock_get, _hide_names(False):
        _get_panel(request_data=request_data)

    mock_get.assert_called_once_with(request_data)


# --------------------------------------------------------------------------
# service — get_indicators_panel_report_csv
# --------------------------------------------------------------------------

_CSV_HEADER = [
    "ID",
    "ID Cidadão",
    "Nº Atendimento",
    "Nome",
    "Data Nascimento",
    "Idade",
    "Endereço",
    "Sexo",
    "Idade Gestacional",
    "CPF",
    "CNS",
    "Unidade de Saúde",
    "Agente de Saúde",
    "Equipe Responsável",
    "CIAP",
    "CID",
    "Data Atendimento Mamografia",
    "Data Atendimento HPV",
    "Data Consulta Gestacional",
    "Data Atendimento Saúde Sexual",
    "Data Vacina HPV",
    "Fez Mamografia",
    "Fez Exame HPV",
    "Fez Vacina HPV",
    "Fez Consulta Saúde Sexual",
    "Fez Consulta Gestacional",
]


def _csv_rows(rows):
    """Run the CSV export and parse the result back into a list of rows."""
    with _repository(rows):
        content = _get_panel_csv(request_data=_request())

    return list(csv.reader(StringIO(content)))


def test_csv_export_of_an_empty_result_is_the_header_alone():
    """With no rows the file still carries the header line."""
    assert _csv_rows([]) == [_CSV_HEADER]


def test_csv_export_header_columns():
    """The header names and their order are part of the download contract."""
    assert _csv_rows([_repository_row()])[0] == _CSV_HEADER


def test_csv_export_row_has_one_value_per_header_column():
    """Header and data rows must stay aligned."""
    rows = _csv_rows([_repository_row()])

    assert len(rows) == 2
    assert len(rows[1]) == len(_CSV_HEADER)


def test_csv_export_writes_the_row_values():
    """The citizen columns are written in the header's order."""
    row = _csv_rows([_repository_row()])[1]

    assert row[:6] == [
        "9000000001",
        "CID-1",
        "90000001",
        "Fulano Beltrano",
        "1990-05-04",
        "36",
    ]
    assert row[11:16] == ["UBS Teste", "Ciclano de Tal", "Equipe Teste", "W78", "Z34"]
    assert row[16:21] == [
        "2026-01-05",
        "2026-02-06",
        "2026-03-07",
        "2026-04-08",
        "2026-06-10",
    ]


@pytest.mark.parametrize(
    "value, expected", [(True, "Sim"), (False, "Não"), (None, "Não se aplica")]
)
def test_csv_export_renders_the_three_indicator_states(value, expected):
    """A null indicator means the citizen is out of the target group."""
    row = _panel_row(has_mammogram=value)

    assert _csv_rows([_repository_row(row=row)])[1][21] == expected


def test_csv_export_renders_every_indicator_column():
    """Each of the five exported indicators gets its own rendered column."""
    row = _panel_row(
        has_mammogram=True,
        has_hpv=False,
        has_vaccine=None,
        has_sexattention_appointment=True,
        has_gestational_appointment=False,
    )

    assert _csv_rows([_repository_row(row=row)])[1][21:26] == [
        "Sim",
        "Não",
        "Não se aplica",
        "Sim",
        "Não",
    ]


def test_csv_export_writes_empty_cells_for_missing_dates():
    """A null date becomes an empty cell rather than the string "None"."""
    row = _panel_row(birthdate=None, hpv_vaccine_date=None)
    cells = _csv_rows([_repository_row(row=row)])[1]

    assert cells[4] == ""
    assert cells[20] == ""


def test_csv_export_overrides_the_requested_limit():
    """The download ignores the paging limit and uses the fixed 10000 cap."""
    request_data = _request(limit=25, offset=0)

    with _repository([]) as mock_get:
        _get_panel_csv(request_data=request_data)

    assert mock_get.call_args.args[0].limit == 10000
    assert request_data.limit == 10000


# --------------------------------------------------------------------------
# service — get_indicators_summary
# --------------------------------------------------------------------------


def test_summary_is_read_for_the_user_schema():
    """The overview is scoped to the schema of the authenticated user."""
    user = User()
    user.id = 7
    user.schema = "demo"
    expected = {"HPV_EXAM": {"value": 12.5, "weight": 20}}

    with patch.object(
        reports_regulation_service.reports_regulation_repository,
        "get_indicators_summary",
        return_value=expected,
    ) as mock_get:
        assert _get_summary(user_context=user) == expected

    mock_get.assert_called_once_with(schema="demo")


# --------------------------------------------------------------------------
# repository — get_indicators_panel_report filters
# --------------------------------------------------------------------------


def test_query_reads_only_the_current_version_of_each_record():
    """The view keeps historical versions: only the current one is reported."""
    recorder, _ = _run_repository_query(_request())

    assert "rel_painel_juntos.v_atual_ficha = true" in _filters_sql(recorder)


def test_query_returns_the_rows_it_finds():
    """The repository hands the rows over untouched."""
    rows = [_repository_row(), _repository_row()]
    _, result = _run_repository_query(_request(), rows=rows)

    assert result == rows


# every reportable indicator and the view column that holds its result
_INDICATOR_COLUMNS = {
    RegulationIndicatorReportEnum.MAMMOGRAM_EXAM.value: "fez_mamografia",
    RegulationIndicatorReportEnum.HPV_EXAM.value: "fez_hpv",
    RegulationIndicatorReportEnum.HPV_VACCINE.value: "fez_vacina",
    RegulationIndicatorReportEnum.SEXUAL_ATTENTION_APPOINTMENT.value: "fez_consulta_sex",
    RegulationIndicatorReportEnum.GESTATIONAL_APPOINTMENT.value: "fez_consulta_gest",
    RegulationIndicatorReportEnum.SEVEN_GESTATIONAL_APPOINTMENTS.value: "fez_sete_consultas_gestacao",
    RegulationIndicatorReportEnum.GESTATIONAL_PRESSURE_MEASUREMENTS.value: "tem_afericao",
    RegulationIndicatorReportEnum.GESTATIONAL_WEIGHT_HEIGHT_MEASUREMENTS.value: "tem_indicador_peso_altura",
}


def test_every_indicator_of_the_enum_is_reportable():
    """A new indicator in the enum must also be filterable in the report."""
    assert set(_INDICATOR_COLUMNS) == {
        indicator.value for indicator in RegulationIndicatorReportEnum
    }


@pytest.mark.parametrize("indicator, column", list(_INDICATOR_COLUMNS.items()))
def test_query_restricts_the_rows_to_the_target_group_of_the_indicator(
    indicator, column
):
    """A null indicator means "not applicable", so those rows are excluded."""
    recorder, _ = _run_repository_query(_request(indicator=indicator))

    assert f"rel_painel_juntos.{column} IS NOT NULL" in _filters_sql(recorder)


@pytest.mark.parametrize("indicator, column", list(_INDICATOR_COLUMNS.items()))
@pytest.mark.parametrize("has_indicator, literal", [(True, "true"), (False, "false")])
def test_query_filters_by_the_indicator_result_when_asked(
    indicator, column, has_indicator, literal
):
    """``has_indicator`` narrows the target group to who did (or did not) do it."""
    recorder, _ = _run_repository_query(
        _request(indicator=indicator, has_indicator=has_indicator)
    )
    filters = _filters_sql(recorder)

    assert f"rel_painel_juntos.{column} IS NOT NULL" in filters
    assert f"rel_painel_juntos.{column} = {literal}" in filters


def test_query_without_has_indicator_keeps_the_whole_target_group():
    """Omitting ``has_indicator`` reports both who did and who did not."""
    recorder, _ = _run_repository_query(_request())
    filters = _filters_sql(recorder)

    assert "rel_painel_juntos.fez_hpv IS NOT NULL" in filters
    assert "rel_painel_juntos.fez_hpv = true" not in filters
    assert "rel_painel_juntos.fez_hpv = false" not in filters


def test_query_ignores_the_indicator_columns_of_the_other_indicators():
    """Only the requested indicator constrains the rows."""
    recorder, _ = _run_repository_query(
        _request(indicator=RegulationIndicatorReportEnum.HPV_VACCINE.value)
    )
    filters = _filters_sql(recorder)

    assert "rel_painel_juntos.fez_vacina IS NOT NULL" in filters
    assert "rel_painel_juntos.fez_hpv IS NOT NULL" not in filters
    assert "rel_painel_juntos.fez_mamografia IS NOT NULL" not in filters


def test_query_with_an_unknown_indicator_applies_no_indicator_filter():
    """An unrecognized indicator only leaves the current-version filter."""
    recorder, _ = _run_repository_query(_request(indicator="NOT_AN_INDICATOR"))

    assert _filters_sql(recorder) == ["rel_painel_juntos.v_atual_ficha = true"]


@pytest.mark.parametrize(
    "field, value, expected_sql",
    [
        ("name", "maria", "lower(rel_painel_juntos.nome) LIKE lower('%maria%')"),
        (
            "health_unit",
            "ubs",
            "lower(rel_painel_juntos.unidadedesaude) LIKE lower('%ubs%')",
        ),
        (
            "health_team",
            "equipe",
            "lower(rel_painel_juntos.equiperesponsavel) LIKE lower('%equipe%')",
        ),
        (
            "health_agent",
            "agente",
            "lower(rel_painel_juntos.agentesaude) LIKE lower('%agente%')",
        ),
    ],
)
def test_query_text_filters_match_anywhere_and_ignore_case(field, value, expected_sql):
    """Free-text filters are case-insensitive "contains" searches."""
    recorder, _ = _run_repository_query(_request(**{field: value}))

    assert expected_sql in _filters_sql(recorder)


@pytest.mark.parametrize(
    "field, value, expected_sql",
    [
        ("cpf", "00000000000", "rel_painel_juntos.cpf = '00000000000'"),
        ("cns", "000000000000000", "rel_painel_juntos.cns = '000000000000000'"),
        ("gender", "F", "rel_painel_juntos.sexo = 'F'"),
        ("age_min", 18, "rel_painel_juntos.idade >= 18"),
        ("age_max", 65, "rel_painel_juntos.idade <= 65"),
    ],
)
def test_query_exact_and_range_filters(field, value, expected_sql):
    """Documents, gender and the age range are matched exactly."""
    recorder, _ = _run_repository_query(_request(**{field: value}))

    assert expected_sql in _filters_sql(recorder)


def test_query_omits_the_filters_that_were_not_requested():
    """An unset optional filter adds nothing to the query."""
    recorder, _ = _run_repository_query(_request())

    assert _filters_sql(recorder) == [
        "rel_painel_juntos.v_atual_ficha = true",
        "rel_painel_juntos.fez_hpv IS NOT NULL",
    ]


def test_query_combines_every_requested_filter():
    """Filters are cumulative (AND), not exclusive."""
    recorder, _ = _run_repository_query(
        _request(
            has_indicator=True,
            name="fulano",
            cpf="00000000000",
            cns="000000000000000",
            age_min=20,
            age_max=40,
            gender="F",
            health_unit="ubs",
            health_team="equipe",
            health_agent="agente",
        )
    )

    assert len(recorder.filters) == 12


def test_query_applies_the_requested_page():
    """Limit and offset are forwarded as the page window."""
    recorder, _ = _run_repository_query(_request(limit=25, offset=75))

    assert recorder.limit_value == 25
    assert recorder.offset_value == 75


# --------------------------------------------------------------------------
# repository — get_indicators_panel_report ordering
# --------------------------------------------------------------------------


def test_query_without_an_order_leaves_the_rows_unordered():
    """No order clause is emitted when none is requested."""
    recorder, _ = _run_repository_query(_request(order=[]))

    assert recorder.orders == []


@pytest.mark.parametrize("direction, expected", [("asc", "ASC"), ("desc", "DESC")])
def test_query_orders_by_name_in_the_requested_direction(direction, expected):
    """Sorting by name follows the requested direction, nulls last."""
    recorder, _ = _run_repository_query(
        _request(order=[{"field": "name", "direction": direction}])
    )

    assert [_sql(o) for o in recorder.orders] == [
        f"rel_painel_juntos.nome {expected} NULLS LAST"
    ]


@pytest.mark.parametrize("direction, expected", [("asc", "DESC"), ("desc", "ASC")])
def test_query_orders_by_birthdate_by_age_instead_of_by_date(direction, expected):
    """The birthdate column is sorted by age: the direction is inverted."""
    recorder, _ = _run_repository_query(
        _request(order=[{"field": "birthdate", "direction": direction}])
    )

    assert [_sql(o) for o in recorder.orders] == [
        f"rel_painel_juntos.dtnascimento {expected} NULLS LAST"
    ]


def test_query_ignores_an_order_on_an_unsupported_field():
    """Only the whitelisted columns can be sorted (no arbitrary attribute access)."""
    recorder, _ = _run_repository_query(
        _request(order=[{"field": "cpf", "direction": "asc"}])
    )

    assert recorder.orders == []


def test_query_keeps_the_requested_order_of_the_sort_clauses():
    """Several sort clauses are applied in the order they were requested."""
    recorder, _ = _run_repository_query(
        _request(
            order=[
                {"field": "name", "direction": "asc"},
                {"field": "birthdate", "direction": "asc"},
            ]
        )
    )

    assert [_sql(o) for o in recorder.orders] == [
        "rel_painel_juntos.nome ASC NULLS LAST",
        "rel_painel_juntos.dtnascimento DESC NULLS LAST",
    ]


# --------------------------------------------------------------------------
# repository — get_indicators_summary
# --------------------------------------------------------------------------

_SUMMARY_WEIGHTS = {
    RegulationIndicatorReportEnum.MAMMOGRAM_EXAM.value: 20,
    RegulationIndicatorReportEnum.HPV_EXAM.value: 20,
    RegulationIndicatorReportEnum.HPV_VACCINE.value: 30,
    RegulationIndicatorReportEnum.SEXUAL_ATTENTION_APPOINTMENT.value: 30,
    RegulationIndicatorReportEnum.GESTATIONAL_APPOINTMENT.value: 9,
}


def _run_summary_query(row, schema="demo"):
    """Run get_indicators_summary against a session returning ``row``."""
    mock_db = MagicMock()
    mock_db.session.execute.return_value.first.return_value = row

    with patch.object(reports_regulation_repository, "db", mock_db):
        result = reports_regulation_repository.get_indicators_summary(schema=schema)

    return result, mock_db


def _summary_row(**overrides):
    """Build the aggregate row returned by the summary query."""
    values = {indicator.lower(): 0 for indicator in _SUMMARY_WEIGHTS}
    values.update({key.lower(): value for key, value in overrides.items()})

    return SimpleNamespace(**values)


def test_summary_query_reads_the_view_of_the_given_schema():
    """The schema is interpolated into the aggregate query."""
    _, mock_db = _run_summary_query(_summary_row(), schema="othertenant")
    query = str(mock_db.session.execute.call_args.args[0])

    assert "othertenant.rel_painel_juntos" in query


def test_summary_with_no_aggregate_row_is_empty():
    """An empty view yields no indicators at all."""
    result, _ = _run_summary_query(None)

    assert result == {}


def test_summary_reports_every_indicator_with_its_weight():
    """The five scored indicators are reported with their fixed weight."""
    result, _ = _run_summary_query(_summary_row())

    assert set(result) == set(_SUMMARY_WEIGHTS)
    for indicator, weight in _SUMMARY_WEIGHTS.items():
        assert result[indicator]["weight"] == weight, indicator


def test_summary_rounds_the_score_to_two_decimals():
    """The score is rounded for display."""
    result, _ = _run_summary_query(
        _summary_row(HPV_EXAM=12.3456, MAMMOGRAM_EXAM=19.999)
    )

    assert result[RegulationIndicatorReportEnum.HPV_EXAM.value]["value"] == 12.35
    assert result[RegulationIndicatorReportEnum.MAMMOGRAM_EXAM.value]["value"] == 20.0


def test_summary_reports_a_missing_score_as_zero():
    """An indicator with no eligible citizen scores zero instead of null."""
    result, _ = _run_summary_query(_summary_row(HPV_VACCINE=None))

    assert result[RegulationIndicatorReportEnum.HPV_VACCINE.value]["value"] == 0


def test_summary_accepts_a_decimal_score():
    """The score arrives as a numeric/Decimal from PostgreSQL."""
    from decimal import Decimal

    result, _ = _run_summary_query(_summary_row(GESTATIONAL_APPOINTMENT=Decimal("8.5")))

    assert (
        result[RegulationIndicatorReportEnum.GESTATIONAL_APPOINTMENT.value]["value"]
        == 8.5
    )


# --------------------------------------------------------------------------
# permission gate
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "service_call",
    [
        lambda: reports_regulation_service.get_indicators_panel_report(
            request_data=_request()
        ),
        lambda: reports_regulation_service.get_indicators_panel_report_csv(
            request_data=_request()
        ),
        lambda: reports_regulation_service.get_indicators_summary(),
    ],
)
def test_reports_require_the_read_reports_permission(service_call):
    """A role without READ_REPORTS cannot reach any of the three endpoints."""
    with acting_as([Role.DISPENSING_MANAGER.value]):
        with pytest.raises(AuthorizationError):
            service_call()


def test_regulator_role_passes_the_gate():
    """REGULATOR holds READ_REPORTS, so the panel report runs."""
    with acting_as([Role.REGULATOR.value]), _repository([]), _hide_names(False):
        result = reports_regulation_service.get_indicators_panel_report(
            request_data=_request()
        )

    assert result == {"count": 0, "data": []}
