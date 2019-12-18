import pytest, json
from io import BytesIO
from mobile import app
from models import User
from unittest.mock import patch
from flask_jwt_extended import (create_access_token)

def make_headers(jwt):
    return {'Authorization': 'Bearer {}'.format(jwt)}

@pytest.fixture
def client():
    client = app.test_client()
    yield client

def test_get(client):
	response = client.get('/patient-name/1234')
	assert response.status_code == 200

def test_no_auth(client):
	response = client.get('/user/name-url')
	assert response.status_code == 401

def user_find(id):
	user = User()
	user.nameUrl = "patient-name"
	return user

@patch('models.User.find', side_effect=user_find)
def test_auth(user, client):
	with app.test_request_context():
		access_token = create_access_token('1')

	response = client.get('/user/name-url', headers=make_headers(access_token))
	data = json.loads(response.data)

	assert response.status_code == 200
	assert data['status'] == 'success'
	assert data['url'] == 'patient-name'