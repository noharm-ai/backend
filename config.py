"""Configuration module for the application."""

from datetime import timedelta
from os import getenv

from models.enums import NoHarmENV


class Config:
    """Configuration class for the application."""

    VERSION = "v6.56-beta"
    FRONTEND_VERSION = "5.1.6"
    ENV = getenv("ENV") or NoHarmENV.DEVELOPMENT.value
    SECRET_KEY = getenv("SECRET_KEY") or "secret_key"
    ENCRYPTION_KEY = getenv("ENCRYPTION_KEY") or None
    API_KEY = getenv("API_KEY") or ""
    SELF_API_URL = getenv("SELF_API_URL") or ""
    APP_URL = getenv("APP_URL")
    APP_DOMAIN = getenv("APP_DOMAIN") or "localhost"
    POTGRESQL_CONNECTION_STRING = (
        getenv("POTGRESQL_CONNECTION_STRING")
        or "postgresql://postgres@localhost/noharm"
    )
    REPORT_CONNECTION_STRING = (
        getenv("REPORT_CONNECTION_STRING") or "postgresql://postgres@localhost/noharm"
    )
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(
        minutes=int(getenv("JWT_ACCESS_TOKEN_EXPIRES", "20"))
    )
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(
        days=int(getenv("JWT_REFRESH_TOKEN_EXPIRES", "30"))
    )
    MAIL_USERNAME = getenv("MAIL_USERNAME") or "user@gmail.com"
    MAIL_PASSWORD = getenv("MAIL_PASSWORD") or "password"
    MAIL_SENDER = getenv("MAIL_SENDER") or "user@gmail.com"
    MAIL_HOST = getenv("MAIL_HOST") or "localhost"

    NIFI_BUCKET_NAME = getenv("NIFI_BUCKET_NAME") or ""
    NIFI_SQS_QUEUE_REGION = getenv("NIFI_SQS_QUEUE_REGION") or ""
    NIFI_LOG_GROUP_NAME = getenv("NIFI_LOG_GROUP_NAME") or ""

    CACHE_BUCKET_NAME = getenv("CACHE_BUCKET_NAME") or ""
    CACHE_BUCKET_ID = getenv("CACHE_BUCKET_ID") or ""
    CACHE_BUCKET_KEY = getenv("CACHE_BUCKET_KEY") or ""

    PRESCRIPTION_PRESENCE_TABLE_NAME = (
        getenv("PRESCRIPTION_PRESENCE_TABLE_NAME") or "noharm_prescription_presence"
    )

    ODOO_API_DB = getenv("ODOO_API_DB") or ""
    ODOO_API_KEY = getenv("ODOO_API_KEY") or ""
    ODOO_API_URL = getenv("ODOO_API_URL") or ""
    ODOO_API_USER = getenv("ODOO_API_USER") or ""

    OPEN_AI_API_ENDPOINT = getenv("OPEN_AI_API_ENDPOINT") or ""
    OPEN_AI_API_KEY = getenv("OPEN_AI_API_KEY") or ""
    OPEN_AI_API_VERSION = getenv("OPEN_AI_API_VERSION") or ""
    OPEN_AI_API_MODEL = getenv("OPEN_AI_API_MODEL") or ""

    MARITACA_API_KEY = getenv("MARITACA_API_KEY") or ""

    REDIS_HOST = getenv("REDIS_HOST") or ""
    REDIS_PORT = getenv("REDIS_PORT") or ""

    SCORES_FUNCTION_NAME = getenv("SCORES_FUNCTION_NAME", "")
    BACKEND_FUNCTION_NAME = getenv("BACKEND_FUNCTION_NAME", "")

    PROTOCOL_AGENT_MODEL_ID = getenv(
        "PROTOCOL_AGENT_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    )
    PROTOCOL_AGENT_REGION = getenv("PROTOCOL_AGENT_REGION", "us-east-1")
    PROTOCOL_AGENT_MAX_TURNS = int(getenv("PROTOCOL_AGENT_MAX_TURNS", "8"))


    FEATURE_CONCILIATION_ALGORITHM = getenv("FEATURE_CONCILIATION_ALGORITHM", "FUZZY")
    # enable only after the onboarding/training app version is released
    FEATURE_USER_ONBOARDING = (
        getenv("FEATURE_USER_ONBOARDING", "false").lower() == "true"
    )
