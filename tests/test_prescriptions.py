from flask.json import jsonify
from conftest import *
from models.appendix import Department
from models.segment import Segment
# from models.prescription import Prescription

from models.prescription import Prescription

# def pres_getall():
#   pres = Prescription()
#   pres.id = 1
#   pres.idHospital = 1
#   pres.name = 'pres'
#   return [pres, pres]

def test_get_prescriptions(client):

    access_token = get_access(client)

    response = client.get('/prescriptions', headers=make_headers(access_token))
    #data = json.loads(response.data)
    assert response.status_code == 200
    # assert data['status'] == 'success'
    # assert data['data'][0]['description'] == 'descript'
    #assert len(data['data']) == 3

def test_get_prescriptions_by_id(client):

    access_token = get_access(client)

    idPrescription = '20'

    response = client.get('/prescriptions/' + idPrescription, headers=make_headers(access_token))
    data = json.loads(response.data)
    prescription = session.query(Prescription).get(idPrescription)

    # breakpoint()

    assert response.status_code == 200
    # assert data['data']['idPrescription'] == '20'
    # assert data['data']['concilia']
    # assert data['data']['bed']
    # assert data['data']['status']