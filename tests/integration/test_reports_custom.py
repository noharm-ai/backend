"""Integration tests for the /reports/custom/list endpoint.

The list endpoint resolves the user who last processed each report. That name
only makes sense for users of the caller's own schema: a NoHarm user from
another schema must stay anonymous, and the report itself must still be listed.

Custom reports live in the schema-local demo.relatorio table. Every row created
here is named with the reserved prefix below, so a single LIKE clause isolates
them. The files behind each report come from S3, so the cache lookup is stubbed.
"""

import json

import pytest
from sqlalchemy import text

from models.enums import ReportStatusEnum, ReportTypeEnum
from services.reports import reports_cache_service
from tests.conftest import session, session_commit
from utils import status

LIST_URL = "/reports/custom/list"

# every report written by this module is named with this prefix
_PREFIX = "ZZTEST_RPTLIST"

# a query that satisfies the SQL guards, used because the SQL is incidental here
_VALID_SQL = "select fkprescricao from demo.prescricao"

# public.usuario row owning the seeded reports — schema demo, same as the caller
_SEED_USER_ID = 1
_SEED_USER_NAME = "Demonstração"

# reserved user placed in another schema to play the cross-schema processor
_OTHER_SCHEMA_EMAIL = "zztest_rptlist_other@example.com"
_OTHER_SCHEMA_NAME = "ZZTEST_RPTLIST Other Schema User"


def _insert_report(name: str, processed_by, active: bool = True) -> int:
    """Insert a processed custom report and return its id."""
    result = session.execute(
        text(
            "INSERT INTO demo.relatorio "
            "(nome, descricao, tp_relatorio, sql, ativo, tp_status, graficos, "
            " processed_at, processed_by, created_at, created_by) "
            "VALUES (:name, :description, :report_type, :sql, :active, :status, "
            " CAST(:graphs AS json), now(), :processed_by, now(), :user) "
            "RETURNING idrelatorio"
        ),
        {
            "name": name,
            "description": "seeded by test_reports_custom",
            "report_type": ReportTypeEnum.CUSTOM.value,
            "sql": _VALID_SQL,
            "active": active,
            "status": ReportStatusEnum.PROCESSED.value,
            "graphs": json.dumps([]),
            "processed_by": processed_by,
            "user": _SEED_USER_ID,
        },
    )
    session_commit()
    return result.scalar()


def _cleanup():
    """Remove every reserved row this module may have created."""
    session.execute(
        text("DELETE FROM demo.relatorio WHERE nome LIKE :prefix"),
        {"prefix": f"{_PREFIX}%"},
    )
    session.execute(
        text("DELETE FROM public.usuario WHERE email = :email"),
        {"email": _OTHER_SCHEMA_EMAIL},
    )
    session_commit()


@pytest.fixture(autouse=True)
def clean_reports():
    """Drop the reserved rows before and after each test."""
    _cleanup()
    yield
    _cleanup()


@pytest.fixture(autouse=True)
def stub_report_cache(monkeypatch):
    """Skip the S3 lookup that lists the files available for each report."""
    monkeypatch.setattr(
        reports_cache_service,
        "list_available_custom_reports",
        lambda schema, id_report: [],  # noqa: ARG005
    )


@pytest.fixture
def other_schema_user() -> int:
    """A user that belongs to a schema other than the caller's."""
    result = session.execute(
        text(
            "INSERT INTO public.usuario (nome, email, senha, schema, config, ativo) "
            "VALUES (:name, :email, 'x', 'zztest_other', CAST(:config AS json), true) "
            "RETURNING idusuario"
        ),
        {
            "name": _OTHER_SCHEMA_NAME,
            "email": _OTHER_SCHEMA_EMAIL,
            "config": json.dumps({"roles": []}),
        },
    )
    session_commit()
    return result.scalar()


def _get_report(client, headers, name: str):
    """Call the list endpoint and return the report stored under a given name."""
    response = client.get(LIST_URL, headers=headers)

    assert response.status_code == status.HTTP_200_OK

    reports = json.loads(response.data)["data"]

    return next((r for r in reports if r["name"] == name), None)


def test_list_names_the_user_who_processed_the_report(client, analyst_headers):
    """A processor from the caller's own schema is named [200 OK]."""
    name = f"{_PREFIX} same schema"
    _insert_report(name=name, processed_by=_SEED_USER_ID)

    report = _get_report(client, analyst_headers, name)

    assert report is not None
    assert report["processed_by_name"] == _SEED_USER_NAME
    assert report["processed_at"] is not None


def test_list_hides_processors_from_other_schemas(
    client, analyst_headers, other_schema_user
):
    """A processor from another schema stays anonymous, report still listed [200 OK]."""
    name = f"{_PREFIX} other schema"
    _insert_report(name=name, processed_by=other_schema_user)

    report = _get_report(client, analyst_headers, name)

    assert report is not None
    assert report["processed_by_name"] is None
    assert report["processed_at"] is not None


def test_list_returns_no_name_when_the_report_was_never_processed(
    client, analyst_headers
):
    """A report without processed_by carries no processor name [200 OK]."""
    name = f"{_PREFIX} never processed"
    _insert_report(name=name, processed_by=None)

    report = _get_report(client, analyst_headers, name)

    assert report is not None
    assert report["processed_by_name"] is None
