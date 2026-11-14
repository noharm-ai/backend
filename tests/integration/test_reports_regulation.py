"""Integration tests for the regulation indicators reports ("Painel Juntos").

Three endpoints read the ``demo.rel_painel_juntos`` table, loaded from
``noharm-create-regulation.sql`` by CI and by ``make test-setup``:

* ``POST /reports/regulation/indicators-panel`` — paginated table of records;
* ``POST /reports/regulation/indicators-panel-csv`` — the same rows as a CSV;
* ``GET /reports/regulation/indicators-summary`` — the weighted score per
  indicator, computed by a raw SQL query.

``tests/unit/test_reports_regulation.py`` covers the mapping and the CSV layout
with a mocked database; here the requests go through the routes, the permission
gate and the real PostgreSQL queries (filters, ordering, the window count and
the summary aggregation).

The seed leaves the table empty, so the module inserts its own fictitious
records (ids prefixed with ``_ID_PREFIX``) and removes them afterwards.
"""

import csv
from io import StringIO

import pytest
from sqlalchemy import text

from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit
from utils import status

PANEL_URL = "/reports/regulation/indicators-panel"
CSV_URL = "/reports/regulation/indicators-panel-csv"
SUMMARY_URL = "/reports/regulation/indicators-summary"

# every record written by this module has an id starting with this prefix
_ID_PREFIX = "9900000"

# fictitious citizens: (id, name, age, gender, health unit, team, agent, cpf,
# fez_mamografia, fez_hpv, fez_vacina, fez_consulta_sex, fez_consulta_gest,
# v_atual_ficha)
_RECORDS = [
    (
        f"{_ID_PREFIX}01",
        "Fulano Beltrano Teste",
        30,
        "F",
        "UBS Centro Teste",
        "Equipe Azul",
        "Agente Ciclano",
        "00000000001",
        True,
        True,
        None,
        True,
        None,
        True,
    ),
    (
        f"{_ID_PREFIX}02",
        "Maria Teste",
        45,
        "F",
        "UBS Centro Teste",
        "Equipe Verde",
        "Agente Beltrano",
        "00000000002",
        False,
        True,
        True,
        False,
        True,
        True,
    ),
    (
        f"{_ID_PREFIX}03",
        "Ciclano de Tal",
        12,
        "M",
        "UBS Bairro Teste",
        "Equipe Azul",
        "Agente Ciclano",
        "00000000003",
        None,
        None,
        False,
        None,
        None,
        True,
    ),
    # an outdated version of a record: never listed by the panel
    (
        f"{_ID_PREFIX}04",
        "Fulano Versao Antiga",
        30,
        "F",
        "UBS Centro Teste",
        "Equipe Azul",
        "Agente Ciclano",
        "00000000004",
        True,
        None,
        None,
        None,
        None,
        False,
    ),
]

_INSERT = text(
    """
    INSERT INTO demo.rel_painel_juntos (
        co_unico_ficha, co_seq_cidadao, nratendimento, nome, dtnascimento, idade,
        sexo, unidadedesaude, equiperesponsavel, agentesaude, cpf,
        dtatendimento_mamo, fez_mamografia, fez_hpv, fez_vacina,
        fez_consulta_sex, fez_consulta_gest, v_atual_ficha
    ) VALUES (
        :id, 1, 1, :name, '1990-01-01', :age,
        :gender, :unit, :team, :agent, :cpf,
        '2026-03-10', :mammo, :hpv, :vaccine,
        :sex, :gest, :current
    )
    """
)


def _delete_records():
    session.execute(
        text("DELETE FROM demo.rel_painel_juntos WHERE co_unico_ficha LIKE :prefix"),
        {"prefix": f"{_ID_PREFIX}%"},
    )
    session_commit()


@pytest.fixture(scope="module", autouse=True)
def panel_records():
    """Insert the fictitious panel records for the module and remove them after"""
    _delete_records()
    for r in _RECORDS:
        session.execute(
            _INSERT,
            {
                "id": r[0],
                "name": r[1],
                "age": r[2],
                "gender": r[3],
                "unit": r[4],
                "team": r[5],
                "agent": r[6],
                "cpf": r[7],
                "mammo": r[8],
                "hpv": r[9],
                "vaccine": r[10],
                "sex": r[11],
                "gest": r[12],
                "current": r[13],
            },
        )
    session_commit()
    yield
    _delete_records()


@pytest.fixture
def no_reports_headers(client):
    """Headers of a user without READ_REPORTS"""
    return make_headers(get_access(client, roles=[Role.DISPENSING_MANAGER.value]))


def _payload(**kwargs):
    """A panel request with every list ordered by name"""
    payload = {
        "indicator": "MAMMOGRAM_EXAM",
        "limit": 50,
        "offset": 0,
        "order": [{"field": "name", "direction": "asc"}],
    }
    payload.update(kwargs)
    return payload


def _panel(client, headers, **kwargs):
    response = client.post(PANEL_URL, json=_payload(**kwargs), headers=headers)
    assert response.status_code == status.HTTP_200_OK, response.get_json()
    return response.get_json()["data"]


def _names(data):
    return [r["name"] for r in data["data"]]


# --- permission gate ---------------------------------------------------------


def test_panel_requires_read_reports(client, no_reports_headers):
    """A user without READ_REPORTS cannot read the panel [401]"""
    response = client.post(PANEL_URL, json=_payload(), headers=no_reports_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_csv_requires_read_reports(client, no_reports_headers):
    """A user without READ_REPORTS cannot download the CSV [401]"""
    response = client.post(CSV_URL, json=_payload(), headers=no_reports_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_summary_requires_read_reports(client, no_reports_headers):
    """A user without READ_REPORTS cannot read the summary [401]"""
    response = client.get(SUMMARY_URL, headers=no_reports_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_panel_rejects_a_request_without_indicator(client, regulator_headers):
    """indicator, limit, offset and order are required [400]"""
    response = client.post(
        PANEL_URL,
        json={"limit": 10, "offset": 0, "order": []},
        headers=regulator_headers,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


# --- panel -------------------------------------------------------------------


def test_panel_lists_only_records_that_apply_to_the_indicator(
    client, regulator_headers
):
    """A record whose indicator is null (not applicable) or that is not the
    current version of the record is left out; the count matches the rows"""
    data = _panel(client, regulator_headers, indicator="MAMMOGRAM_EXAM")

    assert _names(data) == ["Fulano Beltrano Teste", "Maria Teste"]
    assert data["count"] == 2


def test_panel_filters_by_the_indicator_value(client, regulator_headers):
    """has_indicator keeps the records that did (or did not) meet the indicator"""
    done = _panel(
        client, regulator_headers, indicator="HPV_VACCINE", has_indicator=True
    )
    missing = _panel(
        client, regulator_headers, indicator="HPV_VACCINE", has_indicator=False
    )

    assert _names(done) == ["Maria Teste"]
    assert _names(missing) == ["Ciclano de Tal"]


@pytest.mark.parametrize(
    "indicator,expected",
    [
        ("HPV_EXAM", ["Fulano Beltrano Teste", "Maria Teste"]),
        ("SEXUAL_ATTENTION_APPOINTMENT", ["Fulano Beltrano Teste", "Maria Teste"]),
        ("GESTATIONAL_APPOINTMENT", ["Maria Teste"]),
    ],
)
def test_panel_reads_the_column_of_each_indicator(
    client, regulator_headers, indicator, expected
):
    """Each indicator reads its own column"""
    assert _names(_panel(client, regulator_headers, indicator=indicator)) == expected


def test_panel_filters_by_the_citizen_fields(client, regulator_headers):
    """name/unit/team/agent are case-insensitive partial matches; cpf, gender
    and the age range are exact"""
    by_name = _panel(client, regulator_headers, indicator="HPV_VACCINE", name="ciclano")
    by_unit = _panel(
        client, regulator_headers, indicator="HPV_VACCINE", health_unit="bairro"
    )
    by_team = _panel(
        client, regulator_headers, indicator="HPV_EXAM", health_team="verde"
    )
    by_agent = _panel(
        client, regulator_headers, indicator="HPV_EXAM", health_agent="ciclano"
    )
    by_cpf = _panel(client, regulator_headers, indicator="HPV_EXAM", cpf="00000000002")
    by_gender = _panel(client, regulator_headers, indicator="HPV_VACCINE", gender="M")
    by_age = _panel(
        client, regulator_headers, indicator="HPV_EXAM", age_min=40, age_max=50
    )

    assert _names(by_name) == ["Ciclano de Tal"]
    assert _names(by_unit) == ["Ciclano de Tal"]
    assert _names(by_team) == ["Maria Teste"]
    assert _names(by_agent) == ["Fulano Beltrano Teste"]
    assert _names(by_cpf) == ["Maria Teste"]
    assert _names(by_gender) == ["Ciclano de Tal"]
    assert _names(by_age) == ["Maria Teste"]


def test_panel_orders_by_name_in_both_directions(client, regulator_headers):
    """order[] sorts by name ascending or descending"""
    desc = _panel(
        client,
        regulator_headers,
        indicator="HPV_EXAM",
        order=[{"field": "name", "direction": "desc"}],
    )

    assert _names(desc) == ["Maria Teste", "Fulano Beltrano Teste"]


def test_panel_paginates_and_keeps_the_total_count(client, regulator_headers):
    """limit/offset page the rows; count is the total before pagination"""
    page = _panel(client, regulator_headers, indicator="HPV_EXAM", limit=1, offset=1)

    assert _names(page) == ["Maria Teste"]
    assert page["count"] == 2


def test_panel_serializes_the_row(client, regulator_headers):
    """Dates come as ISO strings and the indicator booleans as they are stored"""
    data = _panel(client, regulator_headers, indicator="HPV_VACCINE", name="Maria")
    row = data["data"][0]

    assert row["birthdate"] == "1990-01-01"
    assert row["mammogram_appointment_date"] == "2026-03-10"
    assert row["hpv_vaccine_date"] is None
    assert row["cpf"] == "00000000002"
    assert row["has_mammogram"] is False
    assert row["has_vaccine"] is True
    assert row["has_gestational_appointment"] is True


def test_panel_with_no_match_is_empty(client, regulator_headers):
    """No matching record: empty list and zero count"""
    data = _panel(client, regulator_headers, name="nobody-matches-this")

    assert data == {"count": 0, "data": []}


# --- csv ---------------------------------------------------------------------


def test_csv_download_has_the_filtered_rows(client, regulator_headers):
    """The CSV is served as an attachment, with a header and the filtered rows"""
    response = client.post(
        CSV_URL, json=_payload(indicator="HPV_EXAM"), headers=regulator_headers
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.headers["Content-Type"].startswith("text/csv")
    assert "indicadores.csv" in response.headers["Content-Disposition"]

    rows = list(csv.reader(StringIO(response.get_data(as_text=True))))
    header, body = rows[0], rows[1:]

    assert header[0] == "ID" and header[3] == "Nome"
    assert [r[3] for r in body] == ["Fulano Beltrano Teste", "Maria Teste"]
    # the HPV exam column renders the boolean as Sim/Não
    hpv_col = header.index("Fez Exame HPV")
    assert [r[hpv_col] for r in body] == ["Sim", "Sim"]
    # the vaccine is not applicable to the first record
    vaccine_col = header.index("Fez Vacina HPV")
    assert body[0][vaccine_col] == "Não se aplica"


def test_csv_ignores_the_requested_limit(client, regulator_headers):
    """The download always uses its fixed limit, not the page size"""
    response = client.post(
        CSV_URL,
        json=_payload(indicator="HPV_EXAM", limit=1, offset=0),
        headers=regulator_headers,
    )

    rows = list(csv.reader(StringIO(response.get_data(as_text=True))))

    assert len(rows) == 1 + 2


# --- summary -----------------------------------------------------------------


def test_summary_weights_the_rate_of_each_indicator(client, regulator_headers):
    """Each indicator is (records that met it / records it applies to) × weight,
    over every record of the schema's table"""
    response = client.get(SUMMARY_URL, headers=regulator_headers)

    assert response.status_code == status.HTTP_200_OK
    summary = response.get_json()["data"]

    # mammogram applies to 3 records (the outdated one included), 2 met it
    assert summary["MAMMOGRAM_EXAM"] == {"value": pytest.approx(13.33), "weight": 20}
    # HPV exam: 2 of 2
    assert summary["HPV_EXAM"] == {"value": 20, "weight": 20}
    # HPV vaccine: 1 of 2
    assert summary["HPV_VACCINE"] == {"value": 15, "weight": 30}
    # sexual attention: 1 of 2
    assert summary["SEXUAL_ATTENTION_APPOINTMENT"] == {"value": 15, "weight": 30}
    # gestational appointment: 1 of 1
    assert summary["GESTATIONAL_APPOINTMENT"] == {"value": 9, "weight": 9}
