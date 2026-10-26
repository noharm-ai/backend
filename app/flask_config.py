"""Application configuration classes.

This module defines configuration classes for different environments
(development, production, testing).
"""

import os

from sqlalchemy.engine import make_url

from config import Config
from models.enums import NoHarmENV


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
    SQLALCHEMY_DATABASE_URI = with_psycopg2(Config.POTGRESQL_CONNECTION_STRING)
    SQLALCHEMY_BINDS = {"report": with_psycopg2(Config.REPORT_CONNECTION_STRING)}
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


class ProductionConfig(BaseConfig):
    """Production environment configuration."""

    DEBUG = False


class TestConfig(BaseConfig):
    """Test environment configuration."""

    TESTING = True
    DEBUG = True
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
