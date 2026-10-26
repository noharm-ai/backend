"""Unit tests for app.flask_config (with_psycopg2 driver pin)"""

import pytest
from sqlalchemy.engine import make_url

from app.flask_config import TestConfig, with_psycopg2


def test_bare_postgresql_url_is_pinned_to_psycopg2():
    """SQLAlchemy 2.1 would pick psycopg 3 for a bare URL, so the driver is named."""
    assert (
        with_psycopg2("postgresql://postgres@localhost/noharm")
        == "postgresql+psycopg2://postgres@localhost/noharm"
    )


def test_password_port_and_query_survive_the_rewrite():
    """Only the driver changes: an escaped password, port and query are kept."""
    url = make_url(
        with_psycopg2("postgresql://fulano:p%40ss@db.example.com:5433/noharm?sslmode=require")
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
