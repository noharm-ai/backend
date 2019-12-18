import pytest, json
from io import BytesIO
from mobile import app
from models import User, Department
from unittest.mock import patch, MagicMock
from flask_jwt_extended import (create_access_token)

with app.test_request_context():
	access_token = create_access_token('1')

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
	user.schema = "demo"
	return user

@patch('models.User.find', side_effect=user_find)
def test_name_url(user, client):
	response = client.get('/user/name-url', headers=make_headers(access_token))
	data = json.loads(response.data)

	assert response.status_code == 200
	assert data['status'] == 'success'
	assert data['url'] == 'patient-name'

def dep_getall():
	dep = Department()
	dep.id = 1
	dep.idHospital = 1
	dep.name = 'dep'
	return [dep]

@patch('models.User.find', side_effect=user_find)
@patch('models.Department.getAll', side_effect=dep_getall)
def test_departments(user, department, client):
	response = client.get('/departments', headers=make_headers(access_token))
	data = json.loads(response.data)

	assert response.status_code == 200
	assert data['status'] == 'success'
	assert data['data'][0]['name'] == 'dep'
