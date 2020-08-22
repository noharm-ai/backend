from conftest import *

def getMem(kind, default):
	return default

def test_simple_get(client):
	response = client.get('/patient-name/1234')
	data = json.loads(response.data)

	assert response.status_code == 200
	assert data['idPatient'] == int('1234')

def test_no_auth(client):
	response = client.get('/user/name-url')
	
	assert response.status_code == 401

@patch('models.main.User.find', side_effect=user_find)
@patch('models.appendix.Memory.getMem', side_effect=getMem)
@patch('models.main.dbSession.setSchema', side_effect=setSchema)
def test_name_url(user, memory, main, client):
	response = client.get('/user/name-url', headers=make_headers(access_token))
	data = json.loads(response.data)

	assert response.status_code == 200
	assert data['status'] == 'success'
	assert data['url'] == 'http://localhost/{idPatient}'