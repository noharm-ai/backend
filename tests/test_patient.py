from conftest import *
from models.prescription import Patient

def test_post_patient_permission(client):
    """Teste post /patient/admission - Deve retornar erro [401 UNAUTHORIZED] devido ao usuário utilizado"""
    access_token = get_access(client)

    admission = '5'
    data = {
        "height": "15.0"
    }
    url = 'patient/' + admission

    response = client.post(url, data=json.dumps(data), headers=make_headers(access_token))

    assert response.status_code == 401

def test_post_patient(client):
    """Teste post /patient/admission - Compara dados enviados com dados salvos no banco e valida status_code 200"""
    
    access_token = get_access(client, 'noadmin', 'noadmin')

    admission = '5'
    data = {
        "height": "15.0"
    }
    url = 'patient/' + admission

    response = client.post(url, data=json.dumps(data), headers=make_headers(access_token))
    responseData = json.loads(response.data)['data']
    patient = session.query(Patient).get(admission)

    assert response.status_code == 200
    assert data['height'] == str(patient.height)
    assert admission == str(responseData)

def test_get_notes_by_idAdmission(client):
    """Teste get /notes/idAdmission - Valida status_code 200"""

    access_token = get_access(client, 'noadmin', 'noadmin')

    idAdmission = '5'

    response = client.get('/notes/' + idAdmission, headers=make_headers(access_token))
    data = json.loads(response.data)
    # TODO: Add consulta ao banco de dados e comparar retorno (retornando data: [])

    assert response.status_code == 200

def test_get_exams_by_idAdmission(client):
    """Teste get /exams/idAdmission - Valida status_code 200"""

    access_token = get_access(client)

    idAdmission = '5'

    response = client.get('/exams/' + idAdmission, headers=make_headers(access_token))
    data = json.loads(response.data)    

    # TODO: Add consulta ao banco de dados e comparar retorno (retornando data : {}")

    assert response.status_code == 200
    
    