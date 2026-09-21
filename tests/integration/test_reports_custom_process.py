"""Integration tests for the custom report processing endpoint
(GET /reports/custom/process/<id_report>).

Processing a report is a fire-and-forget lambda invocation: the endpoint hands
the report, the caller and the schema to the backend lambda and flips the report
to PROCESSING so the list endpoint can show it is running. The lambda boundary is
stubbed here, so these tests cover the rules that decide whether the invocation
happens at all:

- the report must exist and be visible to the caller (the same validation the
  download endpoint uses: inactive reports stay closed without
  READ_CUSTOM_REPORTS, and a user who ignores CUSTOM reports is refused);
- a report already PROCESSING is never queued twice;
- a report processed less than an hour ago is throttled, unless the caller holds
  READ_CUSTOM_REPORTS (ADMIN and CURATOR), who may reprocess at will.

Custom reports live in the schema-local demo.relatorio table. Every row created
here is named with the reserved prefix below, so a single LIKE clause isolates
them.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

from models.enums import ReportStatusEnum, ReportTypeEnum
from tests.conftest import session, session_commit
from utils import status

PROCESS_URL = "/reports/custom/process"

# every report written by this module is named with this prefix
_PREFIX = "ZZTEST_RPTPROC"

# a query that satisfies the SQL guards, used because the SQL is incidental here
_VALID_SQL = "select fkprescricao from demo.prescricao"

# the demo user behind every headers fixture of this module
_CALLER_ID = 1
_CALLER_SCHEMA = "demo"


def _insert_report(
    name: str,
    report_status=ReportStatusEnum.PROCESSED.value,
    processed_at=None,
    active: bool = True,
) -> int:
    """Insert a custom report and return its id."""
    result = session.execute(
        text(
            "INSERT INTO demo.relatorio "
            "(nome, descricao, tp_relatorio, sql, ativo, tp_status, graficos, "
            " processed_at, processed_by, created_at, created_by) "
            "VALUES (:name, :description, :report_type, :sql, :active, :status, "
            " CAST(:graphs AS json), :processed_at, :processed_by, now(), :user) "
            "RETURNING idrelatorio"
        ),
        {
            "name": name,
            "description": "seeded by test_reports_custom_process",
            "report_type": ReportTypeEnum.CUSTOM.value,
            "sql": _VALID_SQL,
            "active": active,
            "status": report_status,
            "graphs": json.dumps([]),
            "processed_at": processed_at,
            "processed_by": _CALLER_ID if processed_at is not None else None,
            "user": _CALLER_ID,
        },
    )
    session_commit()
    return result.scalar()


def _report_status(id_report: int):
    """Read the stored status back, bypassing the service."""
    return session.execute(
        text("SELECT tp_status FROM demo.relatorio WHERE idrelatorio = :id"),
        {"id": id_report},
    ).scalar()


def _cleanup():
    """Remove every reserved row this module may have created."""
    session.execute(
        text("DELETE FROM demo.relatorio WHERE nome LIKE :prefix"),
        {"prefix": f"{_PREFIX}%"},
    )
    session.execute(
        text("UPDATE public.usuario SET relatorios = NULL WHERE idusuario = :id"),
        {"id": _CALLER_ID},
    )
    session_commit()


@pytest.fixture(autouse=True)
def clean_reports():
    """Drop the reserved rows before and after each test."""
    _cleanup()
    yield
    _cleanup()


@pytest.fixture
def lambda_client():
    """Stub the backend lambda the processing request is handed to."""
    stub = MagicMock()
    with patch(
        "services.reports.reports_custom_service.aws.get_client", return_value=stub
    ):
        yield stub


def _process(client, headers, id_report: int):
    """Call the processing endpoint for a report."""
    return client.get(f"{PROCESS_URL}/{id_report}", headers=headers)


def test_process_hands_the_report_to_the_lambda(client, analyst_headers, lambda_client):
    """The processing request carries the report, the caller and the schema [200 OK]."""
    id_report = _insert_report(
        name=f"{_PREFIX} never processed",
        report_status=ReportStatusEnum.NOT_PROCESSED.value,
    )

    response = _process(client, analyst_headers, id_report)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] is True

    payload = json.loads(lambda_client.invoke.call_args.kwargs["Payload"])
    assert payload == {
        "command": "lambda_custom_reports.process_custom_report",
        "id_user": _CALLER_ID,
        "id_report": id_report,
        "schema": _CALLER_SCHEMA,
    }
    # fire and forget: the caller polls the report list, it does not wait here
    assert lambda_client.invoke.call_args.kwargs["InvocationType"] == "Event"


def test_process_marks_the_report_as_processing(
    client, analyst_headers, lambda_client  # noqa: ARG001
):
    """The report is flipped to PROCESSING so the list shows it is running [200 OK]."""
    id_report = _insert_report(
        name=f"{_PREFIX} status flip",
        report_status=ReportStatusEnum.NOT_PROCESSED.value,
    )

    response = _process(client, analyst_headers, id_report)

    assert response.status_code == status.HTTP_200_OK
    assert _report_status(id_report) == ReportStatusEnum.PROCESSING.value


def test_process_refuses_a_report_already_processing(
    client, analyst_headers, lambda_client
):
    """A report already running is never queued twice [400 BAD REQUEST]."""
    id_report = _insert_report(
        name=f"{_PREFIX} already processing",
        report_status=ReportStatusEnum.PROCESSING.value,
    )

    response = _process(client, analyst_headers, id_report)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    lambda_client.invoke.assert_not_called()


def test_process_throttles_a_recently_processed_report(
    client, analyst_headers, lambda_client
):
    """A regular reader waits an hour between runs of the same report [400 BAD REQUEST]."""
    id_report = _insert_report(
        name=f"{_PREFIX} throttled",
        processed_at=datetime.now() - timedelta(minutes=30),
    )

    response = _process(client, analyst_headers, id_report)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    lambda_client.invoke.assert_not_called()
    assert _report_status(id_report) == ReportStatusEnum.PROCESSED.value


def test_process_is_allowed_once_the_throttle_window_is_over(
    client, analyst_headers, lambda_client
):
    """Past the one hour window a regular reader may reprocess [200 OK]."""
    id_report = _insert_report(
        name=f"{_PREFIX} throttle expired",
        processed_at=datetime.now() - timedelta(hours=2),
    )

    response = _process(client, analyst_headers, id_report)

    assert response.status_code == status.HTTP_200_OK
    lambda_client.invoke.assert_called_once()


def test_process_ignores_the_throttle_for_curator(
    client, curator_headers, lambda_client
):
    """CURATOR holds READ_CUSTOM_REPORTS, so the throttle does not apply [200 OK]."""
    id_report = _insert_report(
        name=f"{_PREFIX} curator throttle",
        processed_at=datetime.now() - timedelta(minutes=1),
    )

    response = _process(client, curator_headers, id_report)

    assert response.status_code == status.HTTP_200_OK
    lambda_client.invoke.assert_called_once()


def test_process_unknown_report_is_refused(client, analyst_headers, lambda_client):
    """An id with no report behind it is rejected [400 BAD REQUEST]."""
    response = _process(client, analyst_headers, 999999999)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    lambda_client.invoke.assert_not_called()


def test_process_inactive_report_is_refused_for_a_regular_reader(
    client, analyst_headers, lambda_client
):
    """Without READ_CUSTOM_REPORTS an inactive report stays closed [400 BAD REQUEST]."""
    id_report = _insert_report(
        name=f"{_PREFIX} inactive analyst",
        report_status=ReportStatusEnum.NOT_PROCESSED.value,
        active=False,
    )

    response = _process(client, analyst_headers, id_report)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    lambda_client.invoke.assert_not_called()


def test_process_inactive_report_is_allowed_for_curator(
    client, curator_headers, lambda_client
):
    """CURATOR opens inactive reports, the same way the download endpoint does [200 OK]."""
    id_report = _insert_report(
        name=f"{_PREFIX} inactive curator",
        report_status=ReportStatusEnum.NOT_PROCESSED.value,
        active=False,
    )

    response = _process(client, curator_headers, id_report)

    assert response.status_code == status.HTTP_200_OK
    lambda_client.invoke.assert_called_once()


def test_process_is_refused_when_the_user_ignores_custom_reports(
    client, analyst_headers, lambda_client
):
    """A user whose report config ignores CUSTOM cannot process one [401 UNAUTHORIZED]."""
    id_report = _insert_report(
        name=f"{_PREFIX} ignored kind",
        report_status=ReportStatusEnum.NOT_PROCESSED.value,
    )
    session.execute(
        text(
            "UPDATE public.usuario SET relatorios = CAST(:config AS json) "
            "WHERE idusuario = :id"
        ),
        {"config": json.dumps({"ignore": ["CUSTOM"]}), "id": _CALLER_ID},
    )
    session_commit()

    response = _process(client, analyst_headers, id_report)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    lambda_client.invoke.assert_not_called()


def test_process_requires_read_reports(client, config_manager_headers, lambda_client):
    """CONFIG_MANAGER has no report access at all [401 UNAUTHORIZED]."""
    id_report = _insert_report(
        name=f"{_PREFIX} no permission",
        report_status=ReportStatusEnum.NOT_PROCESSED.value,
    )

    response = _process(client, config_manager_headers, id_report)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    lambda_client.invoke.assert_not_called()
    assert _report_status(id_report) == ReportStatusEnum.NOT_PROCESSED.value
