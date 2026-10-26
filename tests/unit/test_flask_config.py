"""Unit tests for app.flask_config (with_psycopg2 driver pin, database secrets)"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.engine import make_url

from app import create_app, flask_config
from app.flask_config import (
    DevelopmentConfig,
    ProductionConfig,
    TestConfig,
    get_config,
    with_psycopg2,
)
from models.enums import NoHarmENV

SECRETS = {
    "test/api_user": {
        "username": "fulano",
        "password": "p@ss:w/rd?#%",
        "host": "db.example.com",
        "port": 5433,
    },
    "test/replica": {
        "username": "ciclano",
        "password": "readonly",
        "host": "replica.example.com",
        "port": "5432",
    },
}


@pytest.fixture
def secrets_mock():
    """Replace the Secrets Manager client and pin the secret ids and database names"""
    client = MagicMock()
    client.get_secret_value.side_effect = lambda SecretId: {
        "SecretString": json.dumps(SECRETS[SecretId])
    }
    with (
        patch.object(flask_config.aws, "get_client", return_value=client) as factory,
        patch.object(flask_config.Config, "DB_SECRET_ID", "test/api_user"),
        patch.object(flask_config.Config, "DB_NAME", "noharm"),
        patch.object(flask_config.Config, "REPORT_DB_SECRET_ID", "test/replica"),
        patch.object(flask_config.Config, "REPORT_DB_NAME", "report"),
    ):
        yield factory


def test_bare_postgresql_url_is_pinned_to_psycopg2():
    """SQLAlchemy 2.1 would pick psycopg 3 for a bare URL, so the driver is named."""
    assert (
        with_psycopg2("postgresql://postgres@localhost/noharm")
        == "postgresql+psycopg2://postgres@localhost/noharm"
    )


def test_password_port_and_query_survive_the_rewrite():
    """Only the driver changes: an escaped password, port and query are kept."""
    url = make_url(
        with_psycopg2(
            "postgresql://fulano:p%40ss@db.example.com:5433/noharm?sslmode=require"
        )
    )

    assert url.drivername == "postgresql+psycopg2"
    assert url.username == "fulano"
    assert url.password == "p@ss"
    assert url.host == "db.example.com"
    assert url.port == 5433
    assert url.database == "noharm"
    assert url.query == {"sslmode": "require"}


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg2://postgres@localhost/noharm",
        "postgresql+psycopg://postgres@localhost/noharm",
    ],
)
def test_url_that_names_a_driver_is_kept(url):
    """An explicit driver is the environment's choice and is not overridden."""
    assert with_psycopg2(url) == url


def test_test_config_connects_with_psycopg2():
    """The test database (and the report bind) go through psycopg2 as well."""
    assert make_url(TestConfig.SQLALCHEMY_DATABASE_URI).get_driver_name() == "psycopg2"
    assert (
        make_url(TestConfig.SQLALCHEMY_BINDS["report"]).get_driver_name() == "psycopg2"
    )


# ---------------------------------------------------------------------------
# database credentials from AWS Secrets Manager
# ---------------------------------------------------------------------------


def test_url_from_secret_escapes_the_password(secrets_mock):
    """A password with URL characters reaches psycopg2 unchanged."""
    url = make_url(flask_config.url_from_secret("test/api_user", "noharm"))

    assert url.drivername == "postgresql+psycopg2"
    assert url.username == "fulano"
    assert url.password == "p@ss:w/rd?#%"
    assert url.host == "db.example.com"
    assert url.port == 5433
    assert url.database == "noharm"
    secrets_mock.assert_called_once_with(
        "secretsmanager", flask_config.Config.DB_SECRET_REGION
    )


def test_database_config_from_secrets_reads_both_secrets(secrets_mock):
    """The main database and the report bind each come from their own secret."""
    config = flask_config.database_config_from_secrets()

    main = make_url(config["SQLALCHEMY_DATABASE_URI"])
    report = make_url(config["SQLALCHEMY_BINDS"]["report"])

    assert (main.username, main.host, main.database) == (
        "fulano",
        "db.example.com",
        "noharm",
    )
    assert (report.username, report.host, report.port, report.database) == (
        "ciclano",
        "replica.example.com",
        5432,
        "report",
    )


def test_secret_connections_verify_the_server_certificate(secrets_mock):
    """Both connections require SSL and check the server against the RDS CA bundle."""
    config = flask_config.database_config_from_secrets()

    for uri in (
        config["SQLALCHEMY_DATABASE_URI"],
        config["SQLALCHEMY_BINDS"]["report"],
    ):
        assert make_url(uri).query == {
            "sslmode": "verify-ca",
            "sslrootcert": flask_config.DB_SSL_ROOT_CERT,
        }


def test_ssl_root_cert_is_an_absolute_path_to_the_bundle():
    """The bundle is found whatever the working directory, and holds only certificates."""
    assert os.path.isabs(flask_config.DB_SSL_ROOT_CERT)
    with open(flask_config.DB_SSL_ROOT_CERT, encoding="utf-8") as bundle:
        content = bundle.read()

    assert "BEGIN CERTIFICATE" in content
    assert "PRIVATE KEY" not in content


DEV_URL = "postgresql://postgres@localhost/noharm_dev"
DEV_REPORT_URL = "postgresql://postgres@localhost/noharm_report"


@pytest.mark.parametrize(
    "env",
    [
        NoHarmENV.PRODUCTION.value,
        NoHarmENV.STAGING.value,
        "homolog",
        NoHarmENV.DEVELOPMENT.value,
    ],
)
def test_environments_read_the_secrets_by_default(secrets_mock, env):
    """Without a connection string, every environment but test reads the secrets."""
    with patch.object(flask_config.Config, "POTGRESQL_CONNECTION_STRING", None):
        config = flask_config.database_config(get_config(env))

    assert make_url(config["SQLALCHEMY_DATABASE_URI"]).host == "db.example.com"
    assert make_url(config["SQLALCHEMY_BINDS"]["report"]).host == "replica.example.com"


@pytest.mark.parametrize(
    "env", [NoHarmENV.PRODUCTION.value, NoHarmENV.STAGING.value, "homolog"]
)
def test_deployed_environments_ignore_the_connection_string(secrets_mock, env):
    """Outside development the connection string env is never used, even when set."""
    with (
        patch.object(flask_config.Config, "POTGRESQL_CONNECTION_STRING", DEV_URL),
        patch.object(flask_config.Config, "REPORT_CONNECTION_STRING", DEV_REPORT_URL),
    ):
        config_class = get_config(env)
        config = flask_config.database_config(config_class)

    assert config_class is ProductionConfig
    assert not hasattr(config_class, "SQLALCHEMY_DATABASE_URI")
    assert make_url(config["SQLALCHEMY_DATABASE_URI"]).host == "db.example.com"


def test_development_may_opt_into_the_connection_string(secrets_mock):
    """Development with POTGRESQL_CONNECTION_STRING set connects with it, without AWS."""
    with (
        patch.object(flask_config.Config, "POTGRESQL_CONNECTION_STRING", DEV_URL),
        patch.object(flask_config.Config, "REPORT_CONNECTION_STRING", DEV_REPORT_URL),
    ):
        config = flask_config.database_config(DevelopmentConfig)

    secrets_mock.assert_not_called()
    assert config["SQLALCHEMY_DATABASE_URI"] == with_psycopg2(DEV_URL)
    assert config["SQLALCHEMY_BINDS"]["report"] == with_psycopg2(DEV_REPORT_URL)


def test_test_config_keeps_its_own_database(secrets_mock):
    """Test never reads the secrets nor the connection string env."""
    with patch.object(flask_config.Config, "POTGRESQL_CONNECTION_STRING", None):
        assert flask_config.database_config(TestConfig) == {}

    secrets_mock.assert_not_called()


def test_create_app_uses_the_secrets_in_production(secrets_mock):
    """The production app connects with the credentials from the secret."""
    app = create_app(NoHarmENV.PRODUCTION.value)

    assert make_url(app.config["SQLALCHEMY_DATABASE_URI"]).host == "db.example.com"
    assert (
        make_url(app.config["SQLALCHEMY_BINDS"]["report"]).host == "replica.example.com"
    )


def test_create_app_does_not_call_aws_in_test(secrets_mock):
    """The test app never reaches Secrets Manager."""
    app = create_app(NoHarmENV.TEST.value)

    secrets_mock.assert_not_called()
    assert app.config["SQLALCHEMY_DATABASE_URI"] == TestConfig.SQLALCHEMY_DATABASE_URI
