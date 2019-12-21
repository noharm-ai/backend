from conftest import *
from models import Department, Segment

def dep_getall():
	dep = Department()
	dep.id = 1
	dep.idHospital = 1
	dep.name = 'dep'
	return [dep, dep]

@patch('models.User.find', side_effect=user_find)
@patch('models.Department.getAll', side_effect=dep_getall)
def test_get_departments(user, department, client):
	response = client.get('/departments', headers=make_headers(access_token))
	data = json.loads(response.data)

	assert response.status_code == 200
	assert data['status'] == 'success'
	assert data['data'][0]['name'] == 'dep'
	assert len(data['data']) == 2

def seg_getall():
	seg = Segment()
	seg.id = 1
	seg.description = 'descript'
	return [seg, seg, seg]

@patch('models.User.find', side_effect=user_find)
@patch('models.Segment.findAll', side_effect=seg_getall)
def test_get_segments(user, segments, client):
	response = client.get('/segments', headers=make_headers(access_token))
	data = json.loads(response.data)

	assert response.status_code == 200
	assert data['status'] == 'success'
	assert data['data'][0]['description'] == 'descript'
	assert len(data['data']) == 3