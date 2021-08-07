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

def test_get_prescriptions_status_code(client):
    """Teste get /prescriptions - Valida status_code 200"""
    access_token = get_access(client)

    response = client.get('/prescriptions', headers=make_headers(access_token))
    #data = json.loads(response.data)
    assert response.status_code == 200
    # assert data['status'] == 'success'
    # assert data['data'][0]['description'] == 'descript'
    #assert len(data['data']) == 3

def test_get_prescriptions_by_id(client):
    """Teste get /prescriptions/id - Compara response data com dados do banco e valida status_code 200"""

    access_token = get_access(client)

    idPrescription = '20'

    response = client.get('/prescriptions/' + idPrescription, headers=make_headers(access_token))
    data = json.loads(response.data)['data']
    prescription = session.query(Prescription).get(idPrescription)

    assert response.status_code == 200
    assert data['idPrescription'] == str(prescription.id)
    assert data['concilia'] == prescription.concilia
    assert data['bed'] == prescription.bed
    assert data['status'] == prescription.status

def test_put_prescriptions_by_id(client):
    """Teste put /prescriptions/id - Compara dados enviados com dados salvos no banco e valida status_code 200"""
    
    access_token = get_access(client, 'noadmin', 'noadmin')

    idPrescription = '20'

    mimetype = 'application/json'
    authorization = 'Bearer {}'.format(access_token)
    headers = {
        'Content-Type': mimetype,
        'Accept': mimetype,
        'Authorization': authorization
    }
    data = {
        "status": "s",
        "notes": "note test",
        "concilia": "s"
    }
    url = 'prescriptions/' + idPrescription

    response = client.put(url, data=json.dumps(data), headers=headers)
    responseData = json.loads(response.data)['data']
    prescription = session.query(Prescription).get(idPrescription)

    assert response.status_code == 200
    assert responseData == str(prescription.id)
    assert data['status'] == prescription.status
    assert data['notes'] == prescription.notes
    assert data['concilia'] == prescription.concilia

def test_put_prescriptions_by_id_permission(client):
    """Teste put /prescriptions/id - Deve retornar erro [401 UNAUTHORIZED] devido ao usuário utilizado"""

    access_token = get_access(client)

    idPrescription = '20'

    mimetype = 'application/json'
    authorization = 'Bearer {}'.format(access_token)
    headers = {
        'Content-Type': mimetype,
        'Accept': mimetype,
        'Authorization': authorization
    }
    data = {
        "status": "s",
        "notes": "note test",
        "concilia": "s"
    }
    url = 'prescriptions/' + idPrescription

    response = client.put(url, data=json.dumps(data), headers=headers)

    assert response.status_code == 401