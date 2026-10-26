"""Application configuration classes.

This module defines configuration classes for different environments
(development, production, testing).
"""

import json
import os

from sqlalchemy.engine import URL, make_url

from config import Config
from models.enums import NoHarmENV
from utils import aws

# Amazon RDS root CAs; the server certificate must chain to one of them
DB_SSL_ROOT_CERT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "certs.pem"
)


def url_from_secret(secret_id: str, database: str) -> str:
    """Build a psycopg2 connection URL from a database secret in AWS Secrets Manager.

    The secret holds username, password, host and port; the database name is
    not in it and comes from the environment. The connection requires SSL and
    verifies the server certificate against DB_SSL_ROOT_CERT (verify-ca).
    """
    client = aws.get_client("secretsmanager", Config.DB_SECRET_REGION)
    secret = json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"])

    return URL.create(
        "postgresql+psycopg2",
        username=secret["username"],
        password=secret["password"],
        host=secret["host"],
        port=int(secret.get("port") or 5432),
        database=database,
        query={"sslmode": "verify-ca", "sslrootcert": DB_SSL_ROOT_CERT},
    ).render_as_string(hide_password=False)


def database_config_from_secrets() -> dict:
    """Database settings for an environment that reads its credentials from secrets."""
    return {
        "SQLALCHEMY_DATABASE_URI": url_from_secret(Config.DB_SECRET_ID, Config.DB_NAME),
        "SQLALCHEMY_BINDS": {
            "report": url_from_secret(Config.REPORT_DB_SECRET_ID, Config.REPORT_DB_NAME)
        },
    }


def database_config(config_class) -> dict:
    """Database settings resolved when the app is created.

    A config with its own URIs (test) keeps them. Where the connection string
    is allowed (development only), setting POTGRESQL_CONNECTION_STRING opts out
    of the secrets. Everything else reads the secrets.
    """
    if not config_class.DATABASE_FROM_SECRETS:
        return {}

    if config_class.ALLOW_CONNECTION_STRING and Config.POTGRESQL_CONNECTION_STRING:
        return {
            "SQLALCHEMY_DATABASE_URI": with_psycopg2(
                Config.POTGRESQL_CONNECTION_STRING
            ),
            "SQLALCHEMY_BINDS": {
                "report": with_psycopg2(Config.REPORT_CONNECTION_STRING)
            },
        }

    return database_config_from_secrets()


def with_psycopg2(url: str) -> str:
    """Pin a bare postgresql:// URL to the psycopg2 driver.

    SQLAlchemy 2.1 maps a URL without a driver to psycopg (version 3), which
    this application is not ready for (see "Driver" under Database in
    CLAUDE.md). A URL that already names a driver is kept as is.
    """
    parsed = make_url(url)
    if parsed.drivername == "postgresql":
        parsed = parsed.set(drivername="postgresql+psycopg2")
    return parsed.render_as_string(hide_password=False)


class BaseConfig:
    """Base configuration with settings common to all environments."""

    # SQLAlchemy
    # the database URIs are set by create_app (see database_config)
    DATABASE_FROM_SECRETS = True
    ALLOW_CONNECTION_STRING = False
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_recycle": 250,
        "pool_pre_ping": True,
        "pool_size": 20,
        "max_overflow": 30,
    }

    # JWT
    JWT_SECRET_KEY = Config.SECRET_KEY
    JWT_ACCESS_TOKEN_EXPIRES = Config.JWT_ACCESS_TOKEN_EXPIRES
    JWT_REFRESH_TOKEN_EXPIRES = Config.JWT_REFRESH_TOKEN_EXPIRES
    JWT_COOKIE_SAMESITE = "Lax"
    JWT_COOKIE_SECURE = True
    JWT_REFRESH_COOKIE_PATH = "/refresh-token"
    JWT_REFRESH_CSRF_COOKIE_PATH = "/refresh-token"
    JWT_COOKIE_CSRF_PROTECT = False

    # Mail
    MAIL_SERVER = "email-smtp.sa-east-1.amazonaws.com"
    MAIL_PORT = 465
    MAIL_USE_SSL = True
    MAIL_USERNAME = Config.MAIL_USERNAME
    MAIL_PASSWORD = Config.MAIL_PASSWORD

    # CORS
    CORS_ORIGINS = [Config.MAIL_HOST]
    CORS_SUPPORTS_CREDENTIALS = True


class DevelopmentConfig(BaseConfig):
    """Development environment configuration."""

    DEBUG = True
    ALLOW_CONNECTION_STRING = True


class ProductionConfig(BaseConfig):
    """Production (and staging) environment configuration."""

    DEBUG = False


class TestConfig(BaseConfig):
    """Test environment configuration."""

    TESTING = True
    DEBUG = True
    DATABASE_FROM_SECRETS = False
    SQLALCHEMY_DATABASE_URI = with_psycopg2(
        os.getenv("TEST_DATABASE_URL", "postgresql://postgres@localhost/noharm")
    )
    SQLALCHEMY_BINDS = {"report": SQLALCHEMY_DATABASE_URI}


def get_config(config_name=None):
    """Get configuration class based on environment.

    Args:
        config_name: Optional config name override ('development', 'production', 'test')

    Returns:
        Configuration class for the specified environment
    """
    if config_name is None:
        config_name = Config.ENV

    config_map = {
        NoHarmENV.DEVELOPMENT.value: DevelopmentConfig,
        NoHarmENV.PRODUCTION.value: ProductionConfig,
        NoHarmENV.TEST.value: TestConfig,
    }

    return config_map.get(config_name, ProductionConfig)
