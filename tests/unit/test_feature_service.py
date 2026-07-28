"""Unit tests for services.feature_service.

feature_service resolves three kinds of flags — tenant features, per-user
features and system feature flags. Each caches its lookup on Flask's request
global ``g`` and only touches the database on a cache miss. These tests drive
both paths using a request context for ``g`` and a mocked ``db`` session for the
database-backed path.
"""

from unittest.mock import MagicMock, patch

from flask import g

from mobile import app
from models.enums import AppFeatureFlagEnum, FeatureEnum
from services import feature_service


def _query_returning(value):
    """Build a mock db whose Memory/GlobalMemory query resolves to ``value``.

    ``value`` is what ``.first()`` returns (an object exposing ``.value`` or
    ``None`` for a missing row).
    """
    mock_db = MagicMock()
    mock_db.session.query.return_value.filter.return_value.first.return_value = value
    return mock_db


class TestHasFeature:
    """Tests for feature_service.has_feature (tenant features)."""

    def test_returns_true_when_present_in_cache(self):
        """A feature already cached on ``g`` is detected without a db lookup."""
        with app.test_request_context():
            g.features = [FeatureEnum.CONCILIATION.value]
            assert feature_service.has_feature(FeatureEnum.CONCILIATION) is True

    def test_returns_false_when_absent_from_cache(self):
        """A feature missing from the cached list is reported as disabled."""
        with app.test_request_context():
            g.features = [FeatureEnum.CONCILIATION.value]
            assert feature_service.has_feature(FeatureEnum.OAUTH) is False

    def test_loads_and_caches_from_memory_on_miss(self):
        """On a cache miss the feature list is loaded from Memory and cached on g."""
        memory_row = MagicMock(value=[FeatureEnum.OAUTH.value])
        with app.test_request_context():
            with patch.object(feature_service, "db", _query_returning(memory_row)):
                assert feature_service.has_feature(FeatureEnum.OAUTH) is True
            # the loaded list is now cached on g for subsequent calls
            assert g.features == [FeatureEnum.OAUTH.value]

    def test_returns_false_when_memory_row_missing(self):
        """With no Memory row configured, every feature is disabled."""
        with app.test_request_context():
            with patch.object(feature_service, "db", _query_returning(None)):
                assert feature_service.has_feature(FeatureEnum.OAUTH) is False


class TestHasUserFeature:
    """Tests for feature_service.has_user_feature (per-user features)."""

    def test_short_circuits_in_test_env(self):
        """In the test environment user features are always disabled."""
        # Config.ENV is 'test' while running the suite -> early empty return.
        assert not feature_service.has_user_feature(FeatureEnum.OAUTH)

    def test_checks_user_features_outside_test_env(self):
        """Outside the test env the flag is looked up in the cached user list."""
        with app.test_request_context():
            g.user_features = [FeatureEnum.OAUTH.value]
            with patch.object(feature_service, "Config") as mock_config:
                mock_config.ENV = "development"
                assert feature_service.has_user_feature(FeatureEnum.OAUTH) is True
                assert (
                    feature_service.has_user_feature(FeatureEnum.CONCILIATION) is False
                )


class TestHasFeatureFlag:
    """Tests for feature_service.has_feature_flag (system feature flags)."""

    def test_returns_true_when_flag_cached(self):
        """A flag enabled in the cached mapping is reported as enabled."""
        with app.test_request_context():
            g.feature_flags = {AppFeatureFlagEnum.REDIS_CACHE.value: True}
            assert (
                feature_service.has_feature_flag(AppFeatureFlagEnum.REDIS_CACHE) is True
            )

    def test_returns_false_when_flag_absent_from_cache(self):
        """A flag missing from the cached mapping defaults to disabled."""
        with app.test_request_context():
            g.feature_flags = {AppFeatureFlagEnum.REDIS_CACHE.value: True}
            assert (
                feature_service.has_feature_flag(AppFeatureFlagEnum.REDIS_CACHE_EXAMS)
                is False
            )

    def test_loads_and_caches_from_global_memory_on_miss(self):
        """On a cache miss flags are loaded from GlobalMemory and cached on g."""
        memory_row = MagicMock(value={AppFeatureFlagEnum.REDIS_CACHE.value: True})
        with app.test_request_context():
            with patch.object(feature_service, "db", _query_returning(memory_row)):
                assert (
                    feature_service.has_feature_flag(AppFeatureFlagEnum.REDIS_CACHE)
                    is True
                )
            assert g.feature_flags == {AppFeatureFlagEnum.REDIS_CACHE.value: True}

    def test_returns_false_when_global_memory_missing(self):
        """With no GlobalMemory row configured, every flag defaults to disabled."""
        with app.test_request_context():
            with patch.object(feature_service, "db", _query_returning(None)):
                assert (
                    feature_service.has_feature_flag(AppFeatureFlagEnum.REDIS_CACHE)
                    is False
                )
