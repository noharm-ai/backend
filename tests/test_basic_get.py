from conftest import *
from models.appendix import Department
from models.segment import Segment

def dep_getall():
	dep = Department()
	dep.id = 1
	dep.idHospital = 1
	dep.name = 'dep'
	return [dep, dep]

@patch('models.main.User.find', side_effect=user_find)
@patch('models.appendix.Department.getAll', side_effect=dep_getall)
@patch('models.main.dbSession.setSchema', side_effect=setSchema)
def test_get_departments(user, department, main, client):
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

@patch('models.main.User.find', side_effect=user_find)
@patch('models.segment.Segment.findAll', side_effect=seg_getall)
@patch('models.main.dbSession.setSchema', side_effect=setSchema)
def test_get_segments(user, segments, main, client):
	response = client.get('/segments', headers=make_headers(access_token))
	data = json.loads(response.data)

	assert response.status_code == 200
	assert data['status'] == 'success'
	assert data['data'][0]['description'] == 'descript'
	assert len(data['data']) == 3