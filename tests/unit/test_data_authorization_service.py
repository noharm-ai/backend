"""Unit tests for services.data_authorization_service.

``has_segment_authorization`` decides whether a user may access a given
segment. It short-circuits for missing segments and for privileged roles
(MAINTAINER / CHECK_STATIC); otherwise, when the AUTHORIZATION_SEGMENT tenant
feature is enabled, it checks for a matching ``UserAuthorization`` row. These
tests drive every branch with a mocked ``db`` session and a patched
``memory_service`` so no database or request context is required.
"""

from unittest.mock import MagicMock, patch

from models.main import User
from services import data_authorization_service


def _user(roles):
    """Build a User carrying the given role names in its config."""
    user = User()
    user.id = 42
    user.config = {"roles": roles}
    return user


def _db_returning(auth_row):
    """Mock db whose UserAuthorization query resolves ``.first()`` to auth_row."""
    mock_db = MagicMock()
    (
        mock_db.session.query.return_value.filter.return_value.filter.return_value.first.return_value
    ) = auth_row
    return mock_db


def test_returns_true_when_segment_is_none():
    """A missing segment is always authorized, regardless of user."""
    assert (
        data_authorization_service.has_segment_authorization(
            id_segment=None, user=_user([])
        )
        is True
    )


def test_returns_true_for_maintainer_role():
    """A user with the MAINTAINER permission bypasses the feature/db check."""
    with patch.object(
        data_authorization_service.memory_service, "has_feature"
    ) as has_feature:
        result = data_authorization_service.has_segment_authorization(
            id_segment=10, user=_user(["ADMIN"])
        )

    assert result is True
    # privileged roles short-circuit before the feature flag is consulted
    has_feature.assert_not_called()


def test_returns_true_when_feature_disabled():
    """With AUTHORIZATION_SEGMENT off, access is granted without a db lookup."""
    with patch.object(
        data_authorization_service.memory_service, "has_feature", return_value=False
    ):
        with patch.object(data_authorization_service, "db") as mock_db:
            result = data_authorization_service.has_segment_authorization(
                id_segment=10, user=_user(["PRESCRIPTION_ANALYST"])
            )

    assert result is True
    mock_db.session.query.assert_not_called()


def test_returns_true_when_feature_enabled_and_authorization_exists():
    """With the feature on and a matching authorization row, access is granted."""
    with patch.object(
        data_authorization_service.memory_service, "has_feature", return_value=True
    ):
        with patch.object(
            data_authorization_service, "db", _db_returning(MagicMock())
        ):
            result = data_authorization_service.has_segment_authorization(
                id_segment=10, user=_user(["PRESCRIPTION_ANALYST"])
            )

    assert result is True


def test_returns_false_when_feature_enabled_and_no_authorization():
    """With the feature on and no matching row, access is denied."""
    with patch.object(
        data_authorization_service.memory_service, "has_feature", return_value=True
    ):
        with patch.object(data_authorization_service, "db", _db_returning(None)):
            result = data_authorization_service.has_segment_authorization(
                id_segment=10, user=_user(["PRESCRIPTION_ANALYST"])
            )

    assert result is False
