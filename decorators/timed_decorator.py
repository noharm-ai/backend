import time
import logging
from functools import wraps

logging.basicConfig()
logger = logging.getLogger("noharm.performance")


def timed(warn=True):

    def log_time_decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            result = func(*args, **kwargs)
            end = time.time()

            duration = round(end - start, 2)

            logger.debug("PERF: {} ran in {}s".format(func.__name__, duration))

            if warn and duration > 2:
                logger.warning(
                    "PERF_WARNING: {} ran in {}s".format(func.__name__, duration)
                )

            return result

        return wrapper

    return log_time_decorator
