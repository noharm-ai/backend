import logging
import time
import json
from redis.exceptions import TimeoutError

from models.main import redis_client


def get_by_key(key: str):
    try:
        return redis_client.json().get(key)
    except TimeoutError:
        logging.basicConfig()
        logger = logging.getLogger("noharm.backend")
        logger.error(
            f"redis timeout error: {key}",
        )
        return None


def get_range(key: str, days_ago: int):
    now = time.time()
    min_date = now - (days_ago * 24 * 60 * 60)

    try:
        cache_data = redis_client.zrangebyscore(key, min=min_date, max=now)
    except TimeoutError:
        logging.basicConfig()
        logger = logging.getLogger("noharm.backend")
        logger.error(
            f"redis timeout error: {key}",
        )
        return None

    if cache_data:
        result = []
        for i in cache_data:
            result.append(json.loads(i))

        return result

    return None


def get_hgetall(key: str):
    try:
        cache_data = redis_client.hgetall(key)
    except:
        logging.basicConfig()
        logger = logging.getLogger("noharm.backend")
        logger.error(
            f"redis timeout error: {key}",
        )
        return None

    data = {}
    for data_key, data_object in cache_data.items():
        data[data_key] = json.loads(data_object)

    return data
