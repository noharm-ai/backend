"""Integration tests for the /admin/report/copy-source endpoints.

Covers the read side of copying charts between custom reports: which reports are
offered as a copy source, the charts they expose, and — since relatorio is a
schema-local table — who may read a source that lives in another schema.

A throwaway schema holds the foreign source, so the cross-schema path is
exercised against a real second schema instead of a stub.
"""

import json

import pytest
from sqlalchemy import text

from models.enums import ReportStatusEnum, ReportTypeEnum
from tests.conftest import session, session_commit
from utils import status

LIST_URL = "/admin/report/copy-source/list"
GRAPHS_URL = "/admin/report/copy-source/{id_report}/graphs"

# every report written by this module is named with this prefix
_PREFIX = "ZZTEST_RPT_COPY"

# the stored query of the seeded reports; incidental to the copy source
_VALID_SQL = "select fkprescricao from demo.prescricao"

# id of the user that owns the rows seeded by this module
_SEED_USER_ID = 1

# throwaway schema holding the foreign copy source
_FOREIGN_SCHEMA = "zztest_copy"

_A_CHART = {"id": "c1", "type": "bar", "xKeys": ["leito"], "yKeys": ["__count__"]}


def _insert_report(
    name: str,
    graphs=None,
    active: bool = True,
    report_type: int = ReportTypeEnum.CUSTOM.value,
    schema: str = "demo",
    raw_graphs: str = None,
) -> int:
    """Insert a processed custom report and return its id.

    `graphs` is stored as a JSON array; `raw_graphs` is stored verbatim, which is
    how the chart editor writes its configuration (a JSON string inside the JSON
    column).
    """
    if raw_graphs is not None:
        stored = raw_graphs
    else:
        stored = json.dumps(graphs) if graphs is not None else None

    result = session.execute(
        text(
            f"INSERT INTO {schema}.relatorio "
            "(nome, descricao, tp_relatorio, sql, ativo, tp_status, erro, graficos, "
            " processed_at, processed_by, created_at, created_by) "
            "VALUES (:name, :description, :report_type, :sql, :active, :status, null, "
            " CAST(:graphs AS json), now(), :user, now(), :user) "
            "RETURNING idrelatorio"
        ),
        {
            "name": name,
            "description": "seeded by test_admin_report_copy",
            "report_type": report_type,
            "sql": _VALID_SQL,
            "active": active,
            "status": ReportStatusEnum.PROCESSED.value,
            "graphs": stored,
            "user": _SEED_USER_ID,
        },
    )
    return result.scalar()


def _cleanup():
    """Remove every reserved report this module may have created."""
    session.execute(
        text("DELETE FROM demo.relatorio WHERE nome LIKE :prefix"),
        {"prefix": f"{_PREFIX}%"},
    )
    session_commit()


@pytest.fixture(autouse=True)
def clean_reports():
    """Drop the reserved reports before and after each test."""
    _cleanup()
    yield
    _cleanup()


@pytest.fixture(scope="module", autouse=True)
def foreign_schema():
    """A second schema with its own relatorio table, configured in schema_config.

    Without the schema_config row the schema is not readable at all, which is the
    guarantee the "unknown schema" test relies on.
    """
    session.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_FOREIGN_SCHEMA}"))
    session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS {_FOREIGN_SCHEMA}.relatorio "
            "(LIKE demo.relatorio INCLUDING ALL)"
        )
    )
    session.execute(
        text(
            "INSERT INTO public.schema_config "
            "(schema_name, created_at, status, tp_noharm_care, tp_pep, "
            " integracao_retorno, tp_prescalc) "
            "VALUES (:schema, now(), 1, 0, 'OTHER', false, 0) "
            "ON CONFLICT (schema_name) DO NOTHING"
        ),
        {"schema": _FOREIGN_SCHEMA},
    )
    session_commit()

    yield

    session.execute(
        text("DELETE FROM public.schema_config WHERE schema_name = :schema"),
        {"schema": _FOREIGN_SCHEMA},
    )
    session.execute(text(f"DROP SCHEMA IF EXISTS {_FOREIGN_SCHEMA} CASCADE"))
    session_commit()


def _list(client, headers, source_schema=None):
    """Call the copy-source listing endpoint."""
    url = LIST_URL
    if source_schema is not None:
        url = f"{LIST_URL}?sourceSchema={source_schema}"

    return client.get(url, headers=headers)


def _graphs(client, headers, id_report, source_schema=None):
    """Call the copy-source graphs endpoint."""
    url = GRAPHS_URL.format(id_report=id_report)
    if source_schema is not None:
        url = f"{url}?sourceSchema={source_schema}"

    return client.get(url, headers=headers)


def _find(rows, id_report):
    """Return the listed row of a report, or None when it was not offered."""
    return next((row for row in rows if row["id"] == id_report), None)


# ---------------------------------------------------------------------------
# listing copy sources
# ---------------------------------------------------------------------------


def test_list_offers_the_reports_of_the_current_schema(client, admin_headers):
    """Without a source schema the copy sources come from the user's own schema."""
    id_report = _insert_report(name=f"{_PREFIX} own", graphs=[_A_CHART, _A_CHART])
    session_commit()

    response = _list(client, admin_headers)

    assert response.status_code == status.HTTP_200_OK
    row = _find(response.get_json()["data"], id_report)
    assert row["name"] == f"{_PREFIX} own"
    assert row["graphCount"] == 2


def test_list_requires_the_graphs_permission(client, analyst_headers):
    """Listing copy sources without WRITE_CUSTOM_REPORTS_GRAPHS is refused [401]."""
    response = _list(client, analyst_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_list_omits_inactive_reports(client, admin_headers):
    """An inactive report cannot be picked as a copy source."""
    id_report = _insert_report(name=f"{_PREFIX} inactive", active=False)
    session_commit()

    response = _list(client, admin_headers)

    assert response.status_code == status.HTTP_200_OK
    assert _find(response.get_json()["data"], id_report) is None


def test_list_counts_charts_stored_as_a_json_string(client, admin_headers):
    """The chart editor stores a JSON string, so the count still has to work."""
    id_report = _insert_report(
        name=f"{_PREFIX} string graphs", raw_graphs=json.dumps(json.dumps([_A_CHART]))
    )
    session_commit()

    response = _list(client, admin_headers)

    assert response.status_code == status.HTTP_200_OK
    assert _find(response.get_json()["data"], id_report)["graphCount"] == 1


def test_list_of_own_schema_does_not_require_maintainer(client, admin_headers):
    """Naming your own schema explicitly is the same as not naming one at all."""
    id_report = _insert_report(name=f"{_PREFIX} explicit own")
    session_commit()

    response = _list(client, admin_headers, source_schema="demo")

    assert response.status_code == status.HTTP_200_OK
    assert _find(response.get_json()["data"], id_report) is not None


def test_list_of_an_unknown_schema_is_refused(client, admin_headers):
    """A schema missing from schema_config is unreadable even for a maintainer [401]."""
    response = _list(client, admin_headers, source_schema="zztest_does_not_exist")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_list_of_a_malformed_schema_is_refused(client, admin_headers):
    """A schema name that is not a plain identifier never reaches the query [400]."""
    response = _list(client, admin_headers, source_schema="demo;drop")

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_list_reads_the_foreign_schema_for_a_maintainer(client, admin_headers):
    """A maintainer may list the copy sources of another configured schema."""
    id_own = _insert_report(name=f"{_PREFIX} own")
    id_foreign = _insert_report(
        name=f"{_PREFIX} foreign", graphs=[_A_CHART], schema=_FOREIGN_SCHEMA
    )
    session_commit()

    response = _list(client, admin_headers, source_schema=_FOREIGN_SCHEMA)

    assert response.status_code == status.HTTP_200_OK
    rows = response.get_json()["data"]
    assert _find(rows, id_foreign)["name"] == f"{_PREFIX} foreign"
    assert _find(rows, id_own) is None


def test_reading_a_foreign_schema_leaves_the_request_schema_intact(
    client, admin_headers
):
    """The foreign read is isolated, so the next call still sees the own schema."""
    id_own = _insert_report(name=f"{_PREFIX} own")
    _insert_report(name=f"{_PREFIX} foreign", schema=_FOREIGN_SCHEMA)
    session_commit()

    assert (
        _list(client, admin_headers, source_schema=_FOREIGN_SCHEMA).status_code
        == status.HTTP_200_OK
    )

    response = _list(client, admin_headers)

    assert response.status_code == status.HTTP_200_OK
    assert _find(response.get_json()["data"], id_own) is not None


# ---------------------------------------------------------------------------
# reading the charts of a copy source
# ---------------------------------------------------------------------------


def test_graphs_returns_the_stored_charts(client, admin_headers):
    """The charts of a copy source are returned as a list."""
    id_report = _insert_report(name=f"{_PREFIX} graphs", graphs=[_A_CHART])
    session_commit()

    response = _graphs(client, admin_headers, id_report)

    assert response.status_code == status.HTTP_200_OK
    data = response.get_json()["data"]
    assert data["graphs"] == [_A_CHART]
    assert data["sourceSchema"] == "demo"


def test_graphs_parses_charts_stored_as_a_json_string(client, admin_headers):
    """Charts written by the editor arrive as a string and are parsed for the caller."""
    id_report = _insert_report(
        name=f"{_PREFIX} string", raw_graphs=json.dumps(json.dumps([_A_CHART]))
    )
    session_commit()

    response = _graphs(client, admin_headers, id_report)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["graphs"] == [_A_CHART]


@pytest.mark.parametrize(
    "raw_graphs",
    [
        pytest.param(json.dumps("not json"), id="unparseable string"),
        pytest.param(json.dumps({"type": "bar"}), id="object instead of list"),
        pytest.param(None, id="null"),
    ],
)
def test_graphs_of_an_unusable_configuration_is_empty(
    client, admin_headers, raw_graphs
):
    """A configuration that is not a chart list is reported as having no charts."""
    id_report = _insert_report(name=f"{_PREFIX} broken", raw_graphs=raw_graphs)
    session_commit()

    response = _graphs(client, admin_headers, id_report)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["graphs"] == []


def test_graphs_requires_the_graphs_permission(client, analyst_headers):
    """Reading a copy source without WRITE_CUSTOM_REPORTS_GRAPHS is refused [401]."""
    id_report = _insert_report(name=f"{_PREFIX} graphs", graphs=[_A_CHART])
    session_commit()

    response = _graphs(client, analyst_headers, id_report)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_graphs_of_an_unknown_report_is_refused(client, admin_headers):
    """Reading a report that does not exist is a business error [400 BAD REQUEST]."""
    response = _graphs(client, admin_headers, 99999999)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidRecord"


def test_graphs_of_an_inactive_report_is_refused(client, admin_headers):
    """An inactive report is not offered, so it cannot be read directly either [400]."""
    id_report = _insert_report(name=f"{_PREFIX} inactive", active=False)
    session_commit()

    response = _graphs(client, admin_headers, id_report)

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_graphs_of_an_unknown_schema_is_refused(client, admin_headers):
    """An unconfigured schema is unreadable even for a maintainer [401]."""
    id_report = _insert_report(name=f"{_PREFIX} graphs", graphs=[_A_CHART])
    session_commit()

    response = _graphs(
        client, admin_headers, id_report, source_schema="zztest_does_not_exist"
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_graphs_reads_the_foreign_schema_for_a_maintainer(client, admin_headers):
    """A maintainer may read the charts of a report in another configured schema."""
    foreign_chart = {**_A_CHART, "title": "foreign"}
    id_foreign = _insert_report(
        name=f"{_PREFIX} foreign", graphs=[foreign_chart], schema=_FOREIGN_SCHEMA
    )
    session_commit()

    response = _graphs(
        client, admin_headers, id_foreign, source_schema=_FOREIGN_SCHEMA
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.get_json()["data"]
    assert data["graphs"] == [foreign_chart]
    assert data["sourceSchema"] == _FOREIGN_SCHEMA


def test_graphs_does_not_reach_a_foreign_report_through_the_own_schema(
    client, admin_headers
):
    """Without the source schema the id is resolved in the caller's schema only."""
    id_foreign = _insert_report(
        name=f"{_PREFIX} foreign", graphs=[_A_CHART], schema=_FOREIGN_SCHEMA
    )
    session_commit()

    response = _graphs(client, admin_headers, id_foreign)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
