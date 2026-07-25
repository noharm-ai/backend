"""Unit tests for utils.db_utils.run_with_deadlock_retry"""

import sys
import types
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from utils.db_utils import run_with_deadlock_retry


def _deadlock_error():
    """Build an OperationalError that looks like a PostgreSQL deadlock (40P01)."""
    return OperationalError("UPDATE ...", {}, Exception("deadlock detected"))


def _other_error():
    """Build a non-deadlock OperationalError."""
    return OperationalError("UPDATE ...", {}, Exception("connection reset"))


@pytest.fixture
def fake_db():
    """Inject a fake models.main module exposing a mock db session.

    run_with_deadlock_retry does a late ``from models.main import db`` so the
    session can be swapped out without touching the real ORM/app wiring.
    """
    fake_models = types.ModuleType("models")
    fake_main = types.ModuleType("models.main")
    fake_main.db = MagicMock()
    fake_models.main = fake_main
    with patch.dict(sys.modules, {"models": fake_models, "models.main": fake_main}):
        yield fake_main.db


@pytest.fixture(autouse=True)
def no_sleep():
    """Avoid real back-off delays and expose sleep for assertions."""
    with patch("utils.db_utils.time.sleep") as mock_sleep:
        yield mock_sleep


class TestRunWithDeadlockRetry:
    """Teste db_utils - run_with_deadlock_retry"""

    def test_returns_value_without_retry_on_success(self, fake_db, no_sleep):
        """When fn succeeds, its value is returned and nothing is retried"""
        fn = MagicMock(return_value="ok")

        result = run_with_deadlock_retry(fn)

        assert result == "ok"
        fn.assert_called_once()
        fake_db.session.rollback.assert_not_called()
        no_sleep.assert_not_called()

    def test_retries_deadlock_then_succeeds(self, fake_db, no_sleep):
        """A deadlock is retried after a rollback and the later value returned"""
        fn = MagicMock(side_effect=[_deadlock_error(), "recovered"])
        on_retry = MagicMock()

        result = run_with_deadlock_retry(fn, on_retry=on_retry)

        assert result == "recovered"
        assert fn.call_count == 2
        fake_db.session.rollback.assert_called_once()
        on_retry.assert_called_once()
        no_sleep.assert_called_once()

    def test_raises_after_exhausting_retries(self, fake_db, no_sleep):
        """A persistent deadlock is re-raised once retries are exhausted"""
        fn = MagicMock(side_effect=_deadlock_error())

        with pytest.raises(OperationalError):
            run_with_deadlock_retry(fn, max_retries=3)

        assert fn.call_count == 3
        # rollback happens on every retry, i.e. max_retries - 1 times
        assert fake_db.session.rollback.call_count == 2
        assert no_sleep.call_count == 2

    def test_non_deadlock_error_is_not_retried(self, fake_db, no_sleep):
        """A non-deadlock OperationalError is raised immediately"""
        fn = MagicMock(side_effect=_other_error())

        with pytest.raises(OperationalError):
            run_with_deadlock_retry(fn)

        fn.assert_called_once()
        fake_db.session.rollback.assert_not_called()
        no_sleep.assert_not_called()

    def test_exponential_backoff_delays(self, fake_db, no_sleep):
        """Back-off grows exponentially from base_delay across attempts"""
        fn = MagicMock(side_effect=_deadlock_error())

        with pytest.raises(OperationalError):
            run_with_deadlock_retry(fn, max_retries=3, base_delay=0.1)

        delays = [call.args[0] for call in no_sleep.call_args_list]
        assert delays == [pytest.approx(0.1), pytest.approx(0.2)]

    def test_works_without_on_retry_callback(self, fake_db, no_sleep):
        """on_retry is optional and omitting it still retries correctly"""
        fn = MagicMock(side_effect=[_deadlock_error(), "ok"])

        result = run_with_deadlock_retry(fn)

        assert result == "ok"
        assert fn.call_count == 2
        fake_db.session.rollback.assert_called_once()
