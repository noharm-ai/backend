import pytest, json
from mobile import app
from models.main import User
from unittest.mock import patch
from flask_jwt_extended import (create_access_token)

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