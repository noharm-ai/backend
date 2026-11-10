"""Unit tests for prescalc_repository.acquire_admission_lock.

Prescalc serializes its runs per admission with a transaction-scoped advisory
lock. The lock is almost always free, so it is first tried without waiting (a
single statement); only when a concurrent run holds it does prescalc wait,
bounded by lock_timeout (three statements). ``db`` is replaced with a mock
session: the concurrency itself is covered by the integration tests
(tests/integration/test_calc_flows.py).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from repository import prescalc_repository

SCHEMA = "demo"
ADMISSION = 100001


def _db(try_lock: bool, wait_error: Exception | None = None):
    """Mock db: the try lock answers ``try_lock``; the wait for the lock raises
    ``wait_error`` when given"""
    mock_db = MagicMock()

    def execute(statement, params=None):
        sql = str(statement)
        result = MagicMock()
        if "pg_try_advisory_xact_lock" in sql:
            result.scalar.return_value = try_lock
        elif "pg_advisory_xact_lock" in sql and wait_error is not None:
            raise wait_error
        return result

    mock_db.session.execute.side_effect = execute

    return mock_db


def _statements(mock_db) -> list[str]:
    """The statements the mock session executed, in order"""
    return [str(call.args[0]) for call in mock_db.session.execute.call_args_list]


def _lock_error(pgcode: str) -> OperationalError:
    """An OperationalError carrying a postgres error code"""
    return OperationalError("stmt", {}, SimpleNamespace(pgcode=pgcode))


def test_free_lock_is_taken_in_one_statement():
    """A free lock is taken without waiting: one statement, no lock_timeout."""
    mock_db = _db(try_lock=True)

    with patch.object(prescalc_repository, "db", mock_db):
        acquired = prescalc_repository.acquire_admission_lock(
            schema=SCHEMA, admission_number=ADMISSION
        )

    assert acquired is True
    statements = _statements(mock_db)
    assert len(statements) == 1
    assert "pg_try_advisory_xact_lock" in statements[0]
    assert mock_db.session.execute.call_args_list[0].args[1] == {
        "key": f"prescalc:{SCHEMA}:{ADMISSION}"
    }


def test_held_lock_is_waited_for_with_a_timeout():
    """A lock held by a concurrent run is waited for under lock_timeout, which
    is restored afterwards."""
    mock_db = _db(try_lock=False)

    with patch.object(prescalc_repository, "db", mock_db):
        acquired = prescalc_repository.acquire_admission_lock(
            schema=SCHEMA, admission_number=ADMISSION, timeout_seconds=2
        )

    assert acquired is True
    statements = _statements(mock_db)
    assert "pg_try_advisory_xact_lock" in statements[0]
    assert statements[1] == "SET LOCAL lock_timeout = '2000'"
    assert "pg_advisory_xact_lock" in statements[2]
    assert statements[3] == "SET LOCAL lock_timeout = DEFAULT"
    # the same lock in both attempts
    calls = mock_db.session.execute.call_args_list
    assert calls[0].args[1] == calls[2].args[1]


def test_timeout_rolls_back_and_reports_not_acquired():
    """When the wait runs out the aborted transaction is rolled back and the
    caller is told to skip."""
    mock_db = _db(try_lock=False, wait_error=_lock_error("55P03"))

    with patch.object(prescalc_repository, "db", mock_db):
        acquired = prescalc_repository.acquire_admission_lock(
            schema=SCHEMA, admission_number=ADMISSION
        )

    assert acquired is False
    mock_db.session.rollback.assert_called_once()


def test_other_database_errors_are_raised():
    """Only the lock timeout means "skip": any other failure surfaces."""
    mock_db = _db(try_lock=False, wait_error=_lock_error("57014"))

    with patch.object(prescalc_repository, "db", mock_db):
        with pytest.raises(OperationalError):
            prescalc_repository.acquire_admission_lock(
                schema=SCHEMA, admission_number=ADMISSION
            )

    mock_db.session.rollback.assert_not_called()
