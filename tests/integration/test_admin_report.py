"""Integration tests for the /admin/report/<idReport>/graphs endpoint.

Covers admin_report_service.update_report_graphs: the graphs-only patch over a
custom report, its permission requirements and its isolation from the
processing state.

Custom reports live in the schema-local demo.relatorio table. Every row
created here is named with the reserved prefix below, so a single LIKE clause
isolates them.
"""

import json

import pytest
from flask_jwt_extended import create_access_token
from sqlalchemy import text

from mobile import app
from models.enums import ReportStatusEnum, ReportTypeEnum
from security.role import Role
from tests.conftest import make_headers, session, session_commit
from utils import status

GRAPHS_URL = "/admin/report/{id_report}/graphs"

# every report written by this module is named with this prefix
_PREFIX = "ZZTEST_RPT"

# the stored query of the seeded reports; incidental to the graphs patch
_VALID_SQL = "select fkprescricao from demo.prescricao"

# public.usuario id of the user behind the curator_headers fixture
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


def _switched_navigator_headers(schema: str) -> dict:
    """Headers of a NAVIGATOR whose session was switched into another schema.

    Mirrors the claims auth_service._auth_user issues to a NAVIGATOR entering an
    external schema: the active schema differs from the home one in usuario.
    """
    id_user = session.execute(
        text("SELECT idusuario FROM public.usuario WHERE email = 'demo'")
    ).scalar()
    claims = {
        "schema": schema,
        "config": {"roles": [Role.NAVIGATOR.value, Role.VIEWER.value], "features": []},
    }

    with app.app_context():
        token = create_access_token(identity=str(id_user), additional_claims=claims)

    return make_headers(token)


def _patch_graphs(client, headers, id_report, graphs):
    """Call the graphs-only patch endpoint."""
    return client.patch(
        GRAPHS_URL.format(id_report=id_report),
        data=json.dumps({"graphs": graphs}),
        headers=headers,
    )


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


def test_graphs_is_allowed_for_navigator_in_home_schema(
    client, navigator_headers, stored_report
):
    """NAVIGATOR may configure the graphs of a report in its own schema."""
    graphs = [{"type": "pie"}]

    response = _patch_graphs(client, navigator_headers, stored_report, graphs)

    assert response.status_code == status.HTTP_200_OK

    session_commit()
    assert _row(stored_report)["graficos"] == graphs


def test_graphs_is_refused_for_navigator_in_foreign_schema(client, stored_report):
    """A non-maintainer switched into another schema may not edit graphs there [401]."""
    headers = _switched_navigator_headers(schema="zztest_foreign")

    response = _patch_graphs(client, headers, stored_report, [{"type": "bar"}])

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


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
