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
