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

def test_get_prescriptions_by_idPrescription(client):
    """Teste get /prescriptions/idPrescription - Compara response data com dados do banco e valida status_code 200"""

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
    assert len(data['prescription']) > 0

def test_get_prescriptions_drug_by_idPrescription_and_period(client):
    """Teste get /prescriptions/drug/idPrescription/period - Compara response data com dados do banco e valida status_code 200"""

    access_token = get_access(client)

    idPrescription = '20'

    url = '/prescriptions/drug/{0}/period'.format(idPrescription)

    response = client.get(url, headers=make_headers(access_token))
    data = json.loads(response.data)['data']
    # TODO: Add consulta ao banco de dados e comparar retorno (retornando status 200 porém data = [])


    assert response.status_code == 200

def test_put_prescriptions_by_id(client):
    """Teste put /prescriptions/id - Compara dados enviados com dados salvos no banco e valida status_code 200"""
    
    access_token = get_access(client, roles=[])

    idPrescription = '20'
    data = {
        "status": "s",
        "notes": "note test",
        "concilia": "s"
    }
    url = 'prescriptions/' + idPrescription

    response = client.put(url, data=json.dumps(data), headers=make_headers(access_token))
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
    data = {
        "status": "s",
        "notes": "note test",
        "concilia": "s"
    }
    url = 'prescriptions/' + idPrescription

    response = client.put(url, data=json.dumps(data), headers=make_headers(access_token))

    assert response.status_code == 401

def test_get_static_demo_prescription_by_idPrescription(client):
    """Teste get /static/demo/prescription/idPrescription - Valida status_code 200"""
    access_token = get_access(client)
    
    idPrescription = '20'
    
    response = client.get('static/demo/prescription/' + idPrescription, headers=make_headers(access_token))
    data = json.loads(response.data)    
    # TODO: Add consulta ao banco de dados e comparar retorno (retornando status 200 porém data = 20)

    assert response.status_code == 200