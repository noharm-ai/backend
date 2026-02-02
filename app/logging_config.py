"""Logging configuration.

This module configures logging for the application based on environment.
"""

import logging

from config import Config
from models.enums import NoHarmENV


def configure_logging():
    """Configure logging levels based on environment.

    In production: WARNING level for most loggers
    In development/other: DEBUG level for application loggers, INFO for boto
    """
    logging.basicConfig()

    if Config.ENV == NoHarmENV.PRODUCTION.value:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
        logging.getLogger("noharm.backend").setLevel(logging.WARNING)
        logging.getLogger("noharm.performance").setLevel(logging.WARNING)
        logging.getLogger("boto3").setLevel(logging.WARNING)
        logging.getLogger("botocore").setLevel(logging.WARNING)
    else:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
        logging.getLogger("noharm.backend").setLevel(logging.DEBUG)
        logging.getLogger("noharm.performance").setLevel(logging.DEBUG)
        logging.getLogger("boto3").setLevel(logging.INFO)
        logging.getLogger("botocore").setLevel(logging.INFO)
