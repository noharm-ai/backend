"""Integration tests for the /admin/report endpoints.

Covers admin_report_service: the create/update branches of the upsert
routine, the graphs-only patch, and the SQL guards that keep a custom report
restricted to read-only statements over the caller's own schema.

Custom reports live in the schema-local demo.relatorio table. Every row
created here is named with the reserved prefix below, so a single LIKE clause
isolates them.

The /admin/report/list endpoint is not covered: it reads public.vanna_report,
a table the test database (noharm-ai/database) does not create.
"""

import json

import pytest
from sqlalchemy import text

from models.enums import ReportStatusEnum, ReportTypeEnum
from tests.conftest import session, session_commit
from utils import status

UPSERT_URL = "/admin/report"
GRAPHS_URL = "/admin/report/{id_report}/graphs"

# every report written by this module is named with this prefix
_PREFIX = "ZZTEST_RPT"

# a query that satisfies both SQL guards, used whenever the SQL is incidental
_VALID_SQL = "select fkprescricao from demo.prescricao"

# public.usuario id of the users behind the admin_headers/curator_headers fixtures
_ADMIN_USER_ID = 2
_CURATOR_USER_ID = 3

# id of the user that owns the rows seeded by this module
_SEED_USER_ID = 1


def _insert_report(
    name: str,
    sql: str = _VALID_SQL,
    active: bool = True,
    report_status: int = ReportStatusEnum.PROCESSED.value,
    error: str = "previous failure",
    graphs=None,
) -> int:
    """Insert a custom report already in a processed state and return its id.

    Starting from a processed row with an error message makes it observable
    whether an update resets the processing state.
    """
    result = session.execute(
        text(
            "INSERT INTO demo.relatorio "
            "(nome, descricao, tp_relatorio, sql, ativo, tp_status, erro, graficos, "
            " processed_at, processed_by, created_at, created_by) "
            "VALUES (:name, :description, :report_type, :sql, :active, :status, :error, "
            " CAST(:graphs AS json), now(), :user, now(), :user) "
            "RETURNING idrelatorio"
        ),
        {
            "name": name,
            "description": "seeded by test_admin_report",
            "report_type": ReportTypeEnum.CUSTOM.value,
            "sql": sql,
            "active": active,
            "status": report_status,
            "error": error,
            "graphs": json.dumps(graphs) if graphs is not None else None,
            "user": _SEED_USER_ID,
        },
    )
    return result.scalar()


def _row(id_report: int):
    """Return the stored columns of a single report as a mapping."""
    result = session.execute(
        text(
            "SELECT idrelatorio, nome, descricao, tp_relatorio, sql, ativo, tp_status, "
            "       erro, graficos, processed_at, updated_by "
            "FROM demo.relatorio WHERE idrelatorio = :id"
        ),
        {"id": id_report},
    )
    return result.mappings().first()


def _rows_named(name: str):
    """Return every report stored under a given name."""
    result = session.execute(
        text("SELECT idrelatorio FROM demo.relatorio WHERE nome = :name"),
        {"name": name},
    )
    return result.all()


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


@pytest.fixture
def stored_report():
    """A processed custom report available for update."""
    id_report = _insert_report(name=f"{_PREFIX} stored")
    session_commit()
    return id_report


class _Omit:
    """Sentinel telling _upsert to leave an attribute out of the payload."""


_OMIT = _Omit()


def _upsert(client, headers, **overrides):
    """Call the upsert endpoint, defaulting every required attribute."""
    payload = {
        "name": f"{_PREFIX} created",
        "description": "created by test_admin_report",
        "sql": _VALID_SQL,
        "active": True,
    }
    payload.update(overrides)
    payload = {k: v for k, v in payload.items() if v is not _OMIT}

    return client.post(UPSERT_URL, data=json.dumps(payload), headers=headers)


def _patch_graphs(client, headers, id_report, graphs):
    """Call the graphs-only patch endpoint."""
    return client.patch(
        GRAPHS_URL.format(id_report=id_report),
        data=json.dumps({"graphs": graphs}),
        headers=headers,
    )


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


def test_create_requires_the_write_reports_permission(client, analyst_headers):
    """Creating a report without WRITE_CUSTOM_REPORTS is refused [401 UNAUTHORIZED]."""
    response = _upsert(client, analyst_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    session_commit()
    assert _rows_named(f"{_PREFIX} created") == []


def test_create_is_refused_for_curator(client, curator_headers):
    """CURATOR may edit graphs but not the report itself [401 UNAUTHORIZED]."""
    response = _upsert(client, curator_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    session_commit()
    assert _rows_named(f"{_PREFIX} created") == []


def test_create_returns_the_new_report(client, admin_headers):
    """Creating returns the stored identity and the initial processing status."""
    response = _upsert(client, admin_headers)

    assert response.status_code == status.HTTP_200_OK
    data = response.get_json()["data"]
    assert data["id"] is not None
    assert data["name"] == f"{_PREFIX} created"
    assert data["description"] == "created by test_admin_report"
    assert data["active"] is True
    assert data["status"] == ReportStatusEnum.NOT_PROCESSED.value


def test_create_persists_the_custom_report_defaults(client, admin_headers):
    """A created report is typed CUSTOM, left unprocessed and stamped with the author."""
    response = _upsert(client, admin_headers)

    assert response.status_code == status.HTTP_200_OK

    session_commit()
    row = _row(response.get_json()["data"]["id"])
    assert row["nome"] == f"{_PREFIX} created"
    assert row["sql"] == _VALID_SQL
    assert row["tp_relatorio"] == ReportTypeEnum.CUSTOM.value
    assert row["tp_status"] == ReportStatusEnum.NOT_PROCESSED.value
    assert row["ativo"] is True
    assert row["erro"] is None
    assert row["processed_at"] is None


def test_create_honours_the_active_flag(client, admin_headers):
    """A report may be created inactive."""
    response = _upsert(client, admin_headers, active=False)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["active"] is False

    session_commit()
    assert _row(response.get_json()["data"]["id"])["ativo"] is False


def test_create_defaults_to_active(client, admin_headers):
    """Omitting the active attribute creates an active report."""
    response = _upsert(client, admin_headers, active=_OMIT)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["active"] is True


@pytest.mark.parametrize("missing", ["name", "description", "sql"])
def test_create_rejects_a_missing_attribute(client, admin_headers, missing):
    """Name, description and sql are all mandatory [400 BAD REQUEST]."""
    response = _upsert(client, admin_headers, **{missing: _OMIT})

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_create_rejects_a_name_over_the_column_length(client, admin_headers):
    """The name is capped at 150 characters [400 BAD REQUEST]."""
    response = _upsert(client, admin_headers, name=_PREFIX + "x" * 150)

    assert response.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# create: the sql guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "delete from demo.prescricao",
        "insert into demo.marcador (nome) values ('x')",
        "drop table demo.prescricao",
        "truncate demo.prescricao",
        "alter table demo.prescricao add column zztest int",
        "grant all on demo.prescricao to public",
        # postgres can write a query result straight to the filesystem
        "copy (select fkprescricao from demo.prescricao) to '/tmp/out.csv'",
        # ...and the mysql spelling of the same exfiltration
        "select fkprescricao from demo.prescricao into outfile '/tmp/out.csv'",
    ],
)
def test_create_rejects_a_destructive_statement(client, admin_headers, sql):
    """Only read-only statements may be stored [400 BAD REQUEST]."""
    response = _upsert(client, admin_headers, sql=sql)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidSQL"


def test_create_rejects_a_statement_that_does_not_select(client, admin_headers):
    """A query has to start with SELECT or WITH [400 BAD REQUEST]."""
    response = _upsert(client, admin_headers, sql=f"explain {_VALID_SQL}")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidSQL"


def test_create_rejects_multiple_statements(client, admin_headers):
    """Chaining statements with a semicolon is refused [400 BAD REQUEST]."""
    response = _upsert(
        client, admin_headers, sql=f"{_VALID_SQL}; select 1 from demo.prescricao"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidSQL"


def test_create_rejects_a_blank_statement(client, admin_headers):
    """Whitespace is not a query [400 BAD REQUEST]."""
    response = _upsert(client, admin_headers, sql="   ")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidSQL"


def test_create_accepts_a_trailing_semicolon(client, admin_headers):
    """A single statement may end with a semicolon."""
    response = _upsert(client, admin_headers, sql=f"{_VALID_SQL};")

    assert response.status_code == status.HTTP_200_OK


def test_create_accepts_a_common_table_expression(client, admin_headers):
    """A query may start with WITH."""
    sql = f"with base as ({_VALID_SQL}) select fkprescricao from base"

    response = _upsert(client, admin_headers, sql=sql)

    assert response.status_code == status.HTTP_200_OK


def test_create_accepts_a_forbidden_word_inside_a_string_literal(client, admin_headers):
    """A keyword quoted as data is not an operation [200 OK]."""
    response = _upsert(
        client, admin_headers, sql="select 'update' as acao from demo.prescricao"
    )

    assert response.status_code == status.HTTP_200_OK


def test_create_accepts_a_forbidden_word_inside_a_quoted_identifier(
    client, admin_headers
):
    """A keyword used as a column alias is not an operation [200 OK]."""
    response = _upsert(
        client,
        admin_headers,
        sql='select leito as "Data Update" from demo.prescricao',
    )

    assert response.status_code == status.HTTP_200_OK


def test_create_accepts_a_column_name_containing_a_forbidden_word(
    client, admin_headers
):
    """update_at is a column, not an UPDATE statement [200 OK]."""
    response = _upsert(
        client, admin_headers, sql="select update_at from demo.prescricao"
    )

    assert response.status_code == status.HTTP_200_OK


def test_create_ignores_a_forbidden_word_inside_a_comment(client, admin_headers):
    """Comments are stripped before the keyword check [200 OK]."""
    response = _upsert(client, admin_headers, sql=f"{_VALID_SQL} -- delete everything")

    assert response.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# create: the schema guard
# ---------------------------------------------------------------------------


def test_create_rejects_another_schema(client, admin_headers):
    """A report may not read a schema other than the caller's [400 BAD REQUEST]."""
    response = _upsert(
        client, admin_headers, sql="select fkprescricao from hospital_zz.prescricao"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.unauthorizedSchemaAccess"


def test_create_rejects_a_public_table_outside_the_whitelist(client, admin_headers):
    """Only a few public tables are readable [400 BAD REQUEST]."""
    response = _upsert(client, admin_headers, sql="select tipo from public.memoria")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.unauthorizedSchemaAccess"


def test_create_accepts_a_whitelisted_public_table(client, admin_headers):
    """public.substancia is explicitly allowed."""
    response = _upsert(client, admin_headers, sql="select sctid from public.substancia")

    assert response.status_code == status.HTTP_200_OK


def test_create_accepts_a_join_inside_the_own_schema(client, admin_headers):
    """Joining two tables of the caller's schema is allowed."""
    sql = (
        "select p.fkprescricao from demo.prescricao p "
        "inner join demo.presmed pm on pm.fkprescricao = p.fkprescricao"
    )

    response = _upsert(client, admin_headers, sql=sql)

    assert response.status_code == status.HTTP_200_OK


def test_create_rejects_the_catalog_schema(client, admin_headers):
    """Enumerating the database through information_schema is refused [400 BAD REQUEST]."""
    response = _upsert(
        client, admin_headers, sql="select table_name from information_schema.tables"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.unauthorizedSchemaAccess"


def test_create_rejects_a_catalog_name_anywhere_in_the_query(client, admin_headers):
    """The catalog check is a substring match, so even a quoted mention trips it."""
    response = _upsert(
        client,
        admin_headers,
        sql=f"{_VALID_SQL} where prescritor = 'information_schema'",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.unauthorizedSchemaAccess"


def test_create_rejects_a_suspicious_unqualified_table(client, admin_headers):
    """An unqualified table that could resolve elsewhere is refused [400 BAD REQUEST]."""
    response = _upsert(client, admin_headers, sql="select nome from users")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.suspiciousTableAccess"


def test_create_accepts_extract_from_a_qualified_column(client, admin_headers):
    """The FROM inside EXTRACT is not a table reference [200 OK]."""
    sql = "select extract(epoch from p.dtprescricao) from demo.prescricao p"

    response = _upsert(client, admin_headers, sql=sql)

    assert response.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


def test_update_replaces_the_editable_fields(client, admin_headers, stored_report):
    """Sending an id updates the existing report instead of creating one."""
    new_sql = "select leito from demo.prescricao"

    response = _upsert(
        client,
        admin_headers,
        id=stored_report,
        name=f"{_PREFIX} renamed",
        description="renamed by test",
        sql=new_sql,
        active=False,
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["id"] == stored_report

    session_commit()
    row = _row(stored_report)
    assert row["nome"] == f"{_PREFIX} renamed"
    assert row["descricao"] == "renamed by test"
    assert row["sql"] == new_sql
    assert row["ativo"] is False


def test_update_does_not_create_a_second_row(client, admin_headers, stored_report):
    """An update leaves exactly one report behind."""
    response = _upsert(client, admin_headers, id=stored_report, name=f"{_PREFIX} once")

    assert response.status_code == status.HTTP_200_OK

    session_commit()
    assert len(_rows_named(f"{_PREFIX} once")) == 1


def test_update_resets_the_processing_state(client, admin_headers, stored_report):
    """Editing a report queues it for reprocessing and clears the previous error."""
    response = _upsert(client, admin_headers, id=stored_report)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["status"] == ReportStatusEnum.NOT_PROCESSED.value

    session_commit()
    row = _row(stored_report)
    assert row["tp_status"] == ReportStatusEnum.NOT_PROCESSED.value
    assert row["processed_at"] is None
    assert row["erro"] is None


def test_update_stamps_the_current_user(client, admin_headers, stored_report):
    """The updated report records who changed it."""
    response = _upsert(client, admin_headers, id=stored_report)

    assert response.status_code == status.HTTP_200_OK

    session_commit()
    assert _row(stored_report)["updated_by"] == _ADMIN_USER_ID


def test_update_keeps_the_custom_report_type(client, admin_headers, stored_report):
    """An updated report stays typed CUSTOM."""
    response = _upsert(client, admin_headers, id=stored_report)

    assert response.status_code == status.HTTP_200_OK

    session_commit()
    assert _row(stored_report)["tp_relatorio"] == ReportTypeEnum.CUSTOM.value


def test_update_of_an_unknown_report_is_refused(client, admin_headers):
    """Updating a report that does not exist is a business error [400 BAD REQUEST]."""
    response = _upsert(client, admin_headers, id=99999999)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidRecord"


def test_update_validates_the_sql_before_looking_up_the_report(
    client, admin_headers, stored_report
):
    """A rejected query leaves the stored report untouched [400 BAD REQUEST]."""
    response = _upsert(
        client, admin_headers, id=stored_report, sql="delete from demo.prescricao"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidSQL"

    session_commit()
    row = _row(stored_report)
    assert row["sql"] == _VALID_SQL
    assert row["tp_status"] == ReportStatusEnum.PROCESSED.value


# ---------------------------------------------------------------------------
# graphs
# ---------------------------------------------------------------------------


def test_graphs_requires_the_graphs_permission(client, analyst_headers, stored_report):
    """Patching graphs without WRITE_CUSTOM_REPORTS_GRAPHS is refused [401 UNAUTHORIZED]."""
    response = _patch_graphs(client, analyst_headers, stored_report, [{"type": "bar"}])

    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    session_commit()
    assert _row(stored_report)["graficos"] is None


def test_graphs_is_allowed_for_admin(client, admin_headers, stored_report):
    """ADMIN may configure the graphs of a report."""
    graphs = [{"type": "bar", "x": "leito"}]

    response = _patch_graphs(client, admin_headers, stored_report, graphs)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == {"id": stored_report, "graphs": graphs}

    session_commit()
    assert _row(stored_report)["graficos"] == graphs


def test_graphs_is_allowed_for_curator(client, curator_headers, stored_report):
    """CURATOR holds WRITE_CUSTOM_REPORTS_GRAPHS even without WRITE_CUSTOM_REPORTS."""
    graphs = [{"type": "line"}]

    response = _patch_graphs(client, curator_headers, stored_report, graphs)

    assert response.status_code == status.HTTP_200_OK

    session_commit()
    row = _row(stored_report)
    assert row["graficos"] == graphs
    assert row["updated_by"] == _CURATOR_USER_ID


def test_graphs_does_not_touch_the_processing_state(
    client, admin_headers, stored_report
):
    """Graphs are presentation only, so the report is not queued for reprocessing."""
    response = _patch_graphs(client, admin_headers, stored_report, [{"type": "pie"}])

    assert response.status_code == status.HTTP_200_OK

    session_commit()
    row = _row(stored_report)
    assert row["tp_status"] == ReportStatusEnum.PROCESSED.value
    assert row["processed_at"] is not None
    assert row["erro"] == "previous failure"


def test_graphs_replaces_the_previous_configuration(client, admin_headers):
    """Patching overwrites the stored graphs rather than merging them."""
    id_report = _insert_report(name=f"{_PREFIX} with graphs", graphs=[{"type": "bar"}])
    session_commit()

    response = _patch_graphs(client, admin_headers, id_report, [{"type": "area"}])

    assert response.status_code == status.HTTP_200_OK

    session_commit()
    assert _row(id_report)["graficos"] == [{"type": "area"}]


def test_graphs_clears_the_configuration_when_null(client, admin_headers):
    """Sending a null graphs configuration removes the stored one."""
    id_report = _insert_report(name=f"{_PREFIX} clear", graphs=[{"type": "bar"}])
    session_commit()

    response = _patch_graphs(client, admin_headers, id_report, None)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["graphs"] is None

    session_commit()
    assert _row(id_report)["graficos"] is None


def test_graphs_of_an_unknown_report_is_refused(client, admin_headers):
    """Patching a report that does not exist is a business error [400 BAD REQUEST]."""
    response = _patch_graphs(client, admin_headers, 99999999, [{"type": "bar"}])

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidRecord"
