import json
import logging
import time
from contextlib import contextmanager

from redis.exceptions import RedisError

from config import Config
from models.enums import NoHarmENV
from models.main import redis_client


def _log_failure(operation: str, key: str, error: Exception):
    """Log a cache operation that could not be completed"""
    logging.basicConfig()
    logger = logging.getLogger("noharm.backend")
    logger.error(f"redis error on {operation}: {key} ({error})")


@contextmanager
def tolerate_failure(operation: str, key: str):
    """Ignore redis failures: the cache is best effort and must not break the request.

    Wraps a whole group of commands on purpose, so an unreachable server costs a
    single connection timeout instead of one per command.
    """
    try:
        yield
    except RedisError as error:
        _log_failure(operation=operation, key=key, error=error)


def get_by_key(key: str):
    if Config.ENV == NoHarmENV.TEST.value:
        return None
    try:
        return redis_client.json().get(key)
    except RedisError as error:
        _log_failure(operation="get_by_key", key=key, error=error)
        return None


def get_range(key: str, days_ago: int):
    if Config.ENV == NoHarmENV.TEST.value:
        return None
    now = time.time()
    min_date = now - (days_ago * 24 * 60 * 60)

    try:
        cache_data = redis_client.zrangebyscore(key, min=min_date, max=now)
    except RedisError as error:
        _log_failure(operation="get_range", key=key, error=error)
        return None

    if cache_data:
        result = []
        for i in cache_data:
            result.append(json.loads(i))

        return result

    return None


def get_hgetall(key: str):
    if Config.ENV == NoHarmENV.TEST.value:
        return None
    try:
        cache_data = redis_client.hgetall(key)
    except RedisError as error:
        _log_failure(operation="get_hgetall", key=key, error=error)
        return None

    data = {}
    for data_key, data_object in cache_data.items():
        data[data_key] = json.loads(data_object)

    return data
