import time
from unittest.mock import MagicMock, patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from models.enums import NoHarmENV
from models.main import redis_cert_reqs
from services import cache_service


@pytest.fixture
def outside_test_env():
    """Bypass the ENV == test short circuit so the redis calls are actually reached"""
    with patch.object(cache_service.Config, "ENV", NoHarmENV.DEVELOPMENT.value):
        yield


@pytest.fixture
def redis_mock():
    """Replace the redis client used by cache_service"""
    with patch.object(cache_service, "redis_client", MagicMock()) as mock:
        yield mock


@pytest.mark.parametrize(
    "error", [RedisConnectionError("unreachable"), RedisTimeoutError("too slow")]
)
def test_get_by_key_returns_none_on_redis_error(outside_test_env, redis_mock, error):
    """get_by_key degrades to None when redis is unreachable or times out"""
    redis_mock.json.return_value.get.side_effect = error

    assert cache_service.get_by_key(key="schema:1:dados") is None


@pytest.mark.parametrize(
    "error", [RedisConnectionError("unreachable"), RedisTimeoutError("too slow")]
)
def test_get_range_returns_none_on_redis_error(outside_test_env, redis_mock, error):
    """get_range degrades to None when redis is unreachable or times out"""
    redis_mock.zrangebyscore.side_effect = error

    assert cache_service.get_range(key="schema:1:dialise", days_ago=10) is None


@pytest.mark.parametrize(
    "error", [RedisConnectionError("unreachable"), RedisTimeoutError("too slow")]
)
def test_get_hgetall_returns_none_on_redis_error(outside_test_env, redis_mock, error):
    """get_hgetall degrades to None when redis is unreachable or times out"""
    redis_mock.hgetall.side_effect = error

    assert cache_service.get_hgetall(key="schema:1:exames") is None


def test_tolerate_failure_swallows_redis_errors():
    """A failing cache write inside tolerate_failure does not reach the caller"""
    with cache_service.tolerate_failure(operation="refresh", key="schema:1:exames"):
        raise RedisConnectionError("unreachable")


def test_tolerate_failure_reraises_other_errors():
    """tolerate_failure only covers redis failures; real bugs still surface"""
    with pytest.raises(ValueError):
        with cache_service.tolerate_failure(operation="refresh", key="schema:1:exames"):
            raise ValueError("bug in the payload")


def test_redis_skips_certificate_verification_in_development_only():
    """Only development connects without verifying the redis certificate"""
    assert redis_cert_reqs(NoHarmENV.DEVELOPMENT.value) is None

    for env in (NoHarmENV.PRODUCTION, NoHarmENV.STAGING, NoHarmENV.TEST):
        assert redis_cert_reqs(env.value) == "required"


def test_tolerate_failure_stops_at_the_first_failed_command():
    """One unreachable server costs a single failure, not one per command in the block"""
    calls = []

    with cache_service.tolerate_failure(operation="refresh", key="schema:1:exames"):
        for i in range(5):
            calls.append(i)
            raise RedisConnectionError("unreachable")

    assert calls == [0]


# --------------------------------------------------------------------------
# Reading from the cache.
#
# The three readers above are only exercised for their failure paths. What they
# do when redis *answers* is just as load-bearing, because every one of them
# hands its result straight to clinical code: get_range backs the allergy and
# dialysis lookups in clinical_notes_repository, and get_hgetall supplies the
# previous exam results that the renal-function panel compares against. A reader
# that decodes wrong, or that widens its own time window, shows a clinician the
# wrong history rather than failing loudly.
#
# Two conventions matter to callers and are pinned here:
#
# * every reader short circuits to None under ENV=test *before* touching redis,
#   which is why the suite needs no redis server;
# * "nothing cached" is not spelled the same way by all of them — get_range
#   answers None for an empty window while get_hgetall answers an empty dict.
#   Callers branch on truthiness, so both work, but the difference is real and
#   a caller that checks `is None` would behave differently against each.
# --------------------------------------------------------------------------

SECONDS_IN_A_DAY = 24 * 60 * 60


class TestTestEnvShortCircuit:
    """ENV=test never reaches redis, so no test needs a server to talk to."""

    def test_get_by_key_answers_none_without_calling_redis(self, redis_mock):
        """The short circuit is why the suite runs without redis configured."""
        assert cache_service.get_by_key(key="schema:1:dados") is None
        redis_mock.json.assert_not_called()

    def test_get_range_answers_none_without_calling_redis(self, redis_mock):
        """Same short circuit on the sorted-set reader."""
        assert cache_service.get_range(key="schema:1:alergia", days_ago=120) is None
        redis_mock.zrangebyscore.assert_not_called()

    def test_get_hgetall_answers_none_without_calling_redis(self, redis_mock):
        """Same short circuit on the hash reader."""
        assert cache_service.get_hgetall(key="schema:1:exames") is None
        redis_mock.hgetall.assert_not_called()


class TestGetByKey:
    """The RedisJSON document reader."""

    def test_reads_the_document_under_the_key(self, outside_test_env, redis_mock):
        """The value comes back from the JSON API, not from a plain GET."""
        redis_mock.json.return_value.get.return_value = {"name": "zztest"}

        assert cache_service.get_by_key(key="schema:1:dados") == {"name": "zztest"}
        redis_mock.json.return_value.get.assert_called_once_with("schema:1:dados")

    def test_a_missing_document_is_passed_through(self, outside_test_env, redis_mock):
        """RedisJSON answers None for an absent key and that is left alone."""
        redis_mock.json.return_value.get.return_value = None

        assert cache_service.get_by_key(key="schema:1:dados") is None


class TestGetRange:
    """The sorted-set reader behind the allergy and dialysis caches."""

    def test_each_member_is_decoded_from_json(self, outside_test_env, redis_mock):
        """Members are stored as JSON strings; callers expect dicts."""
        redis_mock.zrangebyscore.return_value = [
            '{"dtevolucao": "2024-03-10T00:00:00", "texto": "zztest"}'
        ]

        assert cache_service.get_range(key="schema:1:alergia", days_ago=120) == [
            {"dtevolucao": "2024-03-10T00:00:00", "texto": "zztest"}
        ]

    def test_the_order_redis_returned_is_preserved(self, outside_test_env, redis_mock):
        """Callers re-sort by date themselves, so nothing may be reordered here."""
        redis_mock.zrangebyscore.return_value = ['{"n": 1}', '{"n": 2}', '{"n": 3}']

        results = cache_service.get_range(key="schema:1:alergia", days_ago=120)

        assert [r["n"] for r in results] == [1, 2, 3]

    def test_the_window_starts_days_ago_and_ends_now(
        self, outside_test_env, redis_mock
    ):
        """The score is a unix timestamp, so the window is days converted to seconds."""
        redis_mock.zrangebyscore.return_value = []

        cache_service.get_range(key="schema:1:alergia", days_ago=120)

        scores = redis_mock.zrangebyscore.call_args.kwargs

        assert scores["max"] - scores["min"] == pytest.approx(
            120 * SECONDS_IN_A_DAY, abs=1
        )

    def test_the_window_ends_at_the_present(self, outside_test_env, redis_mock):
        """A window anchored in the past would hide today's notes."""
        redis_mock.zrangebyscore.return_value = []

        cache_service.get_range(key="schema:1:dialise", days_ago=10)

        assert redis_mock.zrangebyscore.call_args.kwargs["max"] == pytest.approx(
            time.time(), abs=5
        )

    def test_the_key_is_passed_through_untouched(self, outside_test_env, redis_mock):
        """The key is schema-scoped by the caller and must not be rewritten."""
        redis_mock.zrangebyscore.return_value = []

        cache_service.get_range(key="demo:12345:alergia", days_ago=1)

        assert redis_mock.zrangebyscore.call_args.args == ("demo:12345:alergia",)

    def test_an_empty_window_answers_none(self, outside_test_env, redis_mock):
        """Nothing in range reads as "no cache", which sends the caller to the database."""
        redis_mock.zrangebyscore.return_value = []

        assert cache_service.get_range(key="schema:1:alergia", days_ago=120) is None


class TestGetHgetall:
    """The hash reader behind the previous-exam-results cache."""

    def test_each_value_is_decoded_from_json(self, outside_test_env, redis_mock):
        """Hash values are JSON strings; the exam panel expects dicts."""
        redis_mock.hgetall.return_value = {"cr": '{"value": 1.2, "date": "2024-03-10"}'}

        assert cache_service.get_hgetall(key="schema:1:exames") == {
            "cr": {"value": 1.2, "date": "2024-03-10"}
        }

    def test_every_field_of_the_hash_is_decoded(self, outside_test_env, redis_mock):
        """One exam type per field, and none of them may be dropped."""
        redis_mock.hgetall.return_value = {
            "cr": '{"value": 1.2}',
            "tgo": '{"value": 40}',
            "plaquetas": '{"value": 150000}',
        }

        result = cache_service.get_hgetall(key="schema:1:exames")

        assert set(result.keys()) == {"cr", "tgo", "plaquetas"}

    def test_field_names_are_left_as_stored(self, outside_test_env, redis_mock):
        """Callers lowercase the exam type themselves, so the case is not touched here."""
        redis_mock.hgetall.return_value = {"CR": '{"value": 1.2}'}

        assert list(cache_service.get_hgetall(key="schema:1:exames")) == ["CR"]

    def test_the_key_is_passed_through_untouched(self, outside_test_env, redis_mock):
        """The key already carries the schema and the patient id."""
        redis_mock.hgetall.return_value = {}

        cache_service.get_hgetall(key="demo:999:exames")

        redis_mock.hgetall.assert_called_once_with("demo:999:exames")

    def test_an_empty_hash_answers_an_empty_dict(self, outside_test_env, redis_mock):
        """Unlike get_range, "nothing cached" here is {} rather than None.

        Both are falsy, which is all the current callers check, but a caller
        written against ``is None`` would read the two readers differently.
        """
        redis_mock.hgetall.return_value = {}

        assert cache_service.get_hgetall(key="schema:1:exames") == {}
