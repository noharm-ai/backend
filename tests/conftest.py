import pytest, json
from mobile import app
from models.main import User
from unittest.mock import patch
from flask_jwt_extended import (create_access_token)

import sys
sys.path.append('..')

from config import Config
import sqlalchemy
from sqlalchemy.orm import sessionmaker

engine = sqlalchemy.create_engine(Config.POTGRESQL_CONNECTION_STRING)
DBSession = sessionmaker(bind=engine)
session = DBSession()
session.connection(execution_options={'schema_translate_map': {None: 'demo'}})

with app.test_request_context():
	access_token = create_access_token('1')

def make_headers(jwt):
    return {'Authorization': 'Bearer {}'.format(jwt)}

def user_find(id):
	user = User()
	user.schema = "demo"
	return user

def setSchema(schema):
	return schema

@pytest.fixture
def client():
    client = app.test_client()
    yield client

def get_access(client):
    mimetype = 'application/json'
    headers = {
        'Content-Type': mimetype,
        'Accept': mimetype
    }
    data = {
        "email": "demo",
        "password": "demo"
    }
    url = '/authenticate'

    response = client.post(url, data=json.dumps(data), headers=headers)
    my_json = response.data.decode('utf8').replace("'", '"')
    data_response = json.loads(my_json)
    access_token = data_response['access_token']
    return access_token

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()

    test_fn = item.obj
    docstring = getattr(test_fn, '__doc__')
    if docstring:
        report.nodeid = docstring
