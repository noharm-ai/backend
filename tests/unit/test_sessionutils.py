"""Unit tests for utils.sessionutils.tryCommit (transaction commit wrapper)."""

from unittest.mock import MagicMock

import pytest

from exception.authorization_error import AuthorizationError
from utils import sessionutils, status


def _make_db():
    """Build a db double whose session records rollback/commit/close/remove calls."""
    db = MagicMock()
    return db


class TestTryCommitNotAllowed:
    """When the operation is not allowed the transaction is rolled back."""

    def test_returns_401_and_rolls_back(self):
        """A disallowed commit rolls back and returns a 401 error response."""
        db = _make_db()

        body, http_status = sessionutils.tryCommit(db, 123, allow=False)

        assert http_status == status.HTTP_401_UNAUTHORIZED
        assert body["status"] == "error"
        assert body["message"] == "Usuário não autorizado"
        db.session.rollback.assert_called_once()
        db.session.commit.assert_not_called()

    def test_does_not_leak_record_id(self):
        """A disallowed commit never echoes back the record id."""
        db = _make_db()

        body, _ = sessionutils.tryCommit(db, 999, allow=False)

        assert "data" not in body


class TestTryCommitSuccess:
    """A successful commit returns the record id and closes the session."""

    def test_returns_200_with_record_id(self):
        """A successful commit returns a 200 response carrying the record id."""
        db = _make_db()

        body, http_status = sessionutils.tryCommit(db, 42)

        assert http_status == status.HTTP_200_OK
        assert body == {"status": "success", "data": 42}

    def test_commits_and_cleans_up_session(self):
        """A successful commit commits once and tears the session down."""
        db = _make_db()

        sessionutils.tryCommit(db, 42)

        db.session.commit.assert_called_once()
        db.session.close.assert_called_once()
        db.session.remove.assert_called_once()
        db.session.rollback.assert_not_called()


class TestTryCommitErrors:
    """Exceptions raised while committing are mapped to error responses."""

    def test_authorization_error_returns_401(self):
        """An AuthorizationError during commit returns a 401 and rolls back."""
        db = _make_db()
        db.session.commit.side_effect = AuthorizationError()

        body, http_status = sessionutils.tryCommit(db, 1)

        assert http_status == status.HTTP_401_UNAUTHORIZED
        assert body["status"] == "error"
        assert body["message"] == "Usuário não autorizado."
        db.session.rollback.assert_called_once()

    def test_assertion_error_returns_400(self):
        """An AssertionError during commit is treated as a bad request (400)."""
        db = _make_db()
        db.session.commit.side_effect = AssertionError("invalid data")

        body, http_status = sessionutils.tryCommit(db, 1)

        assert http_status == status.HTTP_400_BAD_REQUEST
        assert body["status"] == "error"
        db.session.rollback.assert_called_once()

    def test_unexpected_error_returns_500(self):
        """Any other exception during commit surfaces as an internal error (500)."""
        db = _make_db()
        db.session.commit.side_effect = RuntimeError("boom")

        body, http_status = sessionutils.tryCommit(db, 1)

        assert http_status == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert body["status"] == "error"
        db.session.rollback.assert_called_once()

    @pytest.mark.parametrize(
        "error, expected_status",
        [
            (AuthorizationError(), status.HTTP_401_UNAUTHORIZED),
            (AssertionError(), status.HTTP_400_BAD_REQUEST),
            (RuntimeError(), status.HTTP_500_INTERNAL_SERVER_ERROR),
        ],
    )
    def test_session_always_closed_on_error(self, error, expected_status):
        """Whatever the failure, the session is closed and removed."""
        db = _make_db()
        db.session.commit.side_effect = error

        _, http_status = sessionutils.tryCommit(db, 1)

        assert http_status == expected_status
        db.session.close.assert_called_once()
        db.session.remove.assert_called_once()
