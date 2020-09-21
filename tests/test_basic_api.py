from conftest import *

def getMem(kind, default):
	return default

def test_simple_get(client):
	response = client.get('/version')
	data = json.loads(response.data)

	assert response.status_code == 200

def test_no_auth(client):
	response = client.get('/reports')
	
	assert response.status_code == 401

@patch('models.main.User.find', side_effect=user_find)
@patch('models.appendix.Memory.getMem', side_effect=getMem)
@patch('models.main.dbSession.setSchema', side_effect=setSchema)
def test_reports(user, memory, main, client):
	response = client.get('/reports', headers=make_headers(access_token))
	data = json.loads(response.data)

	assert response.status_code == 200
	assert data['status'] == 'success'
	assert data['reports'] == []