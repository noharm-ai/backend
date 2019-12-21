from conftest import *

def test_simple_get(client):
	response = client.get('/patient-name/1234')
	data = json.loads(response.data)

	assert response.status_code == 200
	assert data['idPatient'] == int('1234')

def test_no_auth(client):
	response = client.get('/user/name-url')
	
	assert response.status_code == 401

@patch('models.User.find', side_effect=user_find)
def test_name_url(user, client):
	response = client.get('/user/name-url', headers=make_headers(access_token))
	data = json.loads(response.data)

	assert response.status_code == 200
	assert data['status'] == 'success'
	assert data['url'] == 'patient-name'