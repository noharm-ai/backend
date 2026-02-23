import json
import logging

import pytest
import sqlalchemy
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from config import Config
from models.enums import FeatureEnum, NoHarmENV
from app.flask_config import TestConfig
from mobile import app
from models.main import User


def pytest_configure(config):  # noqa: ARG001
    if Config.ENV != NoHarmENV.TEST.value:
        pytest.exit(
            f"ENV='{Config.ENV}' — tests must run with ENV=test. Use 'make test' instead of 'pytest' directly.",
            returncode=1,
        )

logging.basicConfig()
logging.getLogger("sqlalchemy.engine").setLevel(logging.ERROR)

engine = sqlalchemy.create_engine(TestConfig.SQLALCHEMY_DATABASE_URI)
DBSession = sessionmaker(bind=engine)
session = DBSession()
session.connection(execution_options={"schema_translate_map": {None: "demo"}})


def make_headers(jwt):
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": "Bearer {}".format(jwt),
    }


def session_commit():
    session.commit()
    session.connection(execution_options={"schema_translate_map": {None: "demo"}})


@pytest.fixture
def client():
    client = app.test_client()
    yield client


def get_access(client, email="demo", password="demo", roles=["suporte"]):
    mimetype = "application/json"
    headers = {"Content-Type": mimetype, "Accept": mimetype}
    data = {"email": email, "password": password}
    url = "/authenticate"

    _update_roles(email, roles)

    response = client.post(url, data=json.dumps(data), headers=headers)
    my_json = response.data.decode("utf8").replace("'", '"')
    data_response = json.loads(my_json)
    access_token = data_response["access_token"]

    return access_token


def _update_roles(email, roles):
    user = session.query(User).filter_by(email=email).first()
    if user != None:
        user.config = {"roles": roles, "features": [FeatureEnum.STAGING_ACCESS.value]}
        session_commit()


@pytest.fixture(scope="session", autouse=True)
def clean_test_artifacts():
    """Wipe test-generated rows before and after the test session.

    Seed data is preserved. Test-generated prescriptions use IDs >= 100000
    (see tests/utils/utils_test_prescription.py::test_counters).
    """
    _cleanup()
    yield
    _cleanup()


def _cleanup():
    session.execute(text("DELETE FROM demo.prescricao WHERE fkprescricao >= 100000"))
    session.execute(
        text("DELETE FROM demo.prescricao_audit WHERE fkprescricao >= 100000")
    )

    session.execute(text("DELETE FROM demo.presmed WHERE fkpresmed >= 100000001"))
    session.execute(text("DELETE FROM demo.presmed_audit WHERE fkpresmed >= 100000001"))

    session.execute(text("DELETE FROM demo.usuario WHERE email LIKE 'test%@noharm.ai'"))

    session.execute(
        text("UPDATE demo.prescricao set status = '0' WHERE fkprescricao in (9199, 20)")
    )
    session_commit()
    pass


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()

    test_fn = item.obj
    docstring = getattr(test_fn, "__doc__")
    if docstring:
        report.nodeid = docstring
