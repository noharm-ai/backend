"""Application configuration classes.

This module defines configuration classes for different environments
(development, production, testing).
"""

from config import Config
from models.enums import NoHarmENV


class BaseConfig:
    """Base configuration with settings common to all environments."""

    # SQLAlchemy
    SQLALCHEMY_DATABASE_URI = Config.POTGRESQL_CONNECTION_STRING
    SQLALCHEMY_BINDS = {"report": Config.REPORT_CONNECTION_STRING}
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
    # Override with test database if needed
    SQLALCHEMY_DATABASE_URI = "postgresql://postgres@localhost/noharm"


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
