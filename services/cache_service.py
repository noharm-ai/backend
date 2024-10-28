import logging
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
