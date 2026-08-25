"""Unit tests for auth_service.can_read_foreign_schema_as_maintainer.

The helper decides whether a user may read data out of another tenant's schema —
the check that stands between a copy-source request and a schema_translate_map.
Its rules are: your own schema is always readable, another schema requires
MAINTAINER, and a schema that is not configured is never readable. The roles that
grant chart editing today (ADMIN, CURATOR) all carry MAINTAINER, so the negative
branches are only reachable from here.
"""

from unittest.mock import MagicMock, patch

from models.main import User
from security.role import Role
from services import auth_service


def _user(roles, schema="own_schema"):
    """Build a User carrying the given role names in its config."""
    user = User()
    user.id = 42
    user.schema = schema
    user.config = {"roles": roles}
    return user


def _db_with_schema_config(schema_row):
    """Mock db whose SchemaConfig query resolves ``.first()`` to schema_row."""
    mock_db = MagicMock()
    (mock_db.session.query.return_value.filter.return_value.first.return_value) = (
        schema_row
    )
    return mock_db


def test_own_schema_is_readable_without_any_role():
    """Reading your own schema is not a cross-schema access at all."""
    assert (
        auth_service.can_read_foreign_schema_as_maintainer(
            user=_user([]), target_schema="own_schema"
        )
        is True
    )


def test_foreign_schema_is_refused_without_maintainer():
    """MULTI_SCHEMA alone does not open another tenant's data.

    TRAINING carries MULTI_SCHEMA (and TRAINING_RECORDING) but not MAINTAINER.
    """
    assert (
        auth_service.can_read_foreign_schema_as_maintainer(
            user=_user([Role.TRAINING.value]), target_schema="other_schema"
        )
        is False
    )


def test_foreign_schema_is_refused_for_a_user_without_roles():
    """A user with no roles has no cross-schema access."""
    assert (
        auth_service.can_read_foreign_schema_as_maintainer(
            user=_user([]), target_schema="other_schema"
        )
        is False
    )


def test_maintainer_may_read_a_configured_schema():
    """A maintainer reaches another schema once it is known to schema_config."""
    with patch.object(auth_service, "db", _db_with_schema_config(MagicMock())):
        assert (
            auth_service.can_read_foreign_schema_as_maintainer(
                user=_user([Role.ADMIN.value]), target_schema="other_schema"
            )
            is True
        )


def test_maintainer_may_not_read_an_unconfigured_schema():
    """An unknown schema name is refused before it can reach a query."""
    with patch.object(auth_service, "db", _db_with_schema_config(None)):
        assert (
            auth_service.can_read_foreign_schema_as_maintainer(
                user=_user([Role.ADMIN.value]), target_schema="not_a_schema"
            )
            is False
        )


def test_non_maintainer_never_reaches_the_schema_lookup():
    """The role check comes first, so an unauthorized user costs no query."""
    mock_db = _db_with_schema_config(MagicMock())

    with patch.object(auth_service, "db", mock_db):
        auth_service.can_read_foreign_schema_as_maintainer(
            user=_user([Role.VIEWER.value]), target_schema="other_schema"
        )

    mock_db.session.query.assert_not_called()
