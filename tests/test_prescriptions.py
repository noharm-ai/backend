from conftest import *
from models.appendix import Department
from models.segment import Segment
# from models.prescription import Prescription

# def pres_getall():
#   pres = Prescription()
#   pres.id = 1
#   pres.idHospital = 1
#   pres.name = 'pres'
#   return [pres, pres]


@patch('models.main.User.find', side_effect=user_find)
# @patch('models.prescriptions.Prescriptions.findAll', side_effect=pres_getall)
@patch('models.main.dbSession.setSchema', side_effect=setSchema)
def test_get_prescriptions(user, main, client):
    result = client.post(
        '/authenticate', {"email": "demo", "password": "demo"})
    response = client.get('/prescriptions', headers=make_headers(access_token))
    data = json.loads(response.data)
    print(result)
    assert response.status_code == 200
    # assert data['status'] == 'success'
    # assert data['data'][0]['description'] == 'descript'
    # assert len(data['data']) == 3
