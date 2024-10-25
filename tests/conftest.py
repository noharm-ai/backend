import pytest, json
import logging
import sqlalchemy
from sqlalchemy.orm import sessionmaker

from mobile import app
from models.main import User
from models.enums import FeatureEnum
from config import Config

logging.basicConfig()
logging.getLogger("sqlalchemy.engine").setLevel(logging.ERROR)

engine = sqlalchemy.create_engine(Config.POTGRESQL_CONNECTION_STRING)
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


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()

    test_fn = item.obj
    docstring = getattr(test_fn, "__doc__")
    if docstring:
        report.nodeid = docstring
