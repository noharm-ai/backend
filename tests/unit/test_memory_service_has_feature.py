"""Unit tests for the feature lookups in services.memory_service.

``has_feature`` decides whether a feature is on for the current request: a
feature listed in the logged user's ``config["features"]`` wins, otherwise the
schema-wide ``features`` memory is checked. A missing JWT, a missing user or a
user without config must not break the lookup — it just falls back to the
schema memory. ``has_feature_nouser`` is the same schema-memory check, used
where there is no user (scheduled jobs, static calls).

``User.find``, ``get_jwt_identity`` and the ``db`` session are patched, so no
database or request context is needed.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from models.enums import FeatureEnum
from services import memory_service

FEATURE = FeatureEnum.OAUTH.value
OTHER_FEATURE = FeatureEnum.CONCILIATION.value


def _db_with_features(features):
    """Build a mock db whose ``features`` memory query returns ``features``.

    ``None`` means there is no ``features`` memory row in the schema.
    """
    row = None if features is None else SimpleNamespace(value=features)
    mock_db = MagicMock()
    mock_db.session.query.return_value.filter.return_value.first.return_value = row
    return mock_db


def _has_feature(feature, *, user=None, user_error=None, schema_features=None):
    """Run ``has_feature`` with the given logged user and schema memory."""
    mock_db = _db_with_features(schema_features)
    find = MagicMock(return_value=user, side_effect=user_error)

    with (
        patch.object(memory_service, "get_jwt_identity", return_value=1),
        patch.object(memory_service.User, "find", find),
        patch.object(memory_service, "db", mock_db),
    ):
        return memory_service.has_feature(feature), mock_db


def _user(config):
    """Build a user with the given config."""
    return SimpleNamespace(config=config)


class TestHasFeature:
    """Tests for memory_service.has_feature"""

    def test_user_feature_wins_without_querying_schema(self):
        """A feature in the user's config is on and the schema memory is not read."""
        result, mock_db = _has_feature(
            FEATURE, user=_user({"features": [FEATURE]}), schema_features=[]
        )

        assert result is True
        mock_db.session.query.assert_not_called()

    def test_falls_back_to_schema_features(self):
        """A feature missing from the user's config is on if the schema enables it."""
        result, _ = _has_feature(
            FEATURE,
            user=_user({"features": [OTHER_FEATURE]}),
            schema_features=[FEATURE],
        )

        assert result is True

    def test_off_when_neither_user_nor_schema_has_it(self):
        """A feature absent from the user's config and the schema memory is off."""
        result, _ = _has_feature(
            FEATURE,
            user=_user({"features": [OTHER_FEATURE]}),
            schema_features=[OTHER_FEATURE],
        )

        assert result is False

    def test_off_when_schema_has_no_features_memory(self):
        """Without a ``features`` memory row every non-user feature is off."""
        result, _ = _has_feature(FEATURE, user=_user({}), schema_features=None)

        assert result is False

    @pytest.mark.parametrize(
        "config",
        [None, {}, {"roles": ["VIEWER"]}],
        ids=["no-config", "empty-config", "config-without-features"],
    )
    def test_user_without_features_uses_schema(self, config):
        """A user config with no feature list falls back to the schema memory."""
        result, _ = _has_feature(FEATURE, user=_user(config), schema_features=[FEATURE])

        assert result is True

    @pytest.mark.parametrize(
        "user_error",
        [RuntimeError("no jwt in request"), AttributeError("user not found")],
        ids=["no-jwt", "lookup-error"],
    )
    def test_user_lookup_failure_uses_schema(self, user_error):
        """If the user cannot be resolved, the schema memory still decides."""
        enabled, _ = _has_feature(
            FEATURE, user_error=user_error, schema_features=[FEATURE]
        )
        disabled, _ = _has_feature(
            FEATURE, user_error=user_error, schema_features=[OTHER_FEATURE]
        )

        assert enabled is True
        assert disabled is False

    def test_unknown_user_uses_schema(self):
        """``User.find`` returning nothing behaves like a user without features."""
        result, _ = _has_feature(FEATURE, user=None, schema_features=[FEATURE])

        assert result is True


class TestHasFeatureNoUser:
    """Tests for memory_service.has_feature_nouser"""

    @pytest.mark.parametrize(
        ("schema_features", "expected"),
        [
            ([FEATURE], True),
            ([OTHER_FEATURE, FEATURE], True),
            ([OTHER_FEATURE], False),
            ([], False),
            (None, False),
        ],
        ids=["enabled", "enabled-among-others", "other-only", "empty", "no-memory"],
    )
    def test_reads_schema_features(self, schema_features, expected):
        """The result depends only on the schema ``features`` memory."""
        with patch.object(memory_service, "db", _db_with_features(schema_features)):
            assert memory_service.has_feature_nouser(FEATURE) is expected

    def test_does_not_look_up_the_user(self):
        """No user is resolved, so it is safe to call outside a request."""
        with (
            patch.object(memory_service, "db", _db_with_features([FEATURE])),
            patch.object(memory_service.User, "find") as find,
            patch.object(memory_service, "get_jwt_identity") as identity,
        ):
            assert memory_service.has_feature_nouser(FEATURE) is True

        find.assert_not_called()
        identity.assert_not_called()
