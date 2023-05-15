from conftest import *
from datetime import datetime

from models.appendix import InterventionReason
from models.prescription import Intervention

def test_get_interventions(client):
    """Teste get /intervention/search - Compara quantidade de intervenções enviadas com quantidade salva no banco e valida status_code 200"""
    
    access_token = get_access(client)
    interventions = session.query(Intervention).count()

    data = {
        "startDate": datetime.today().isoformat()
    }

    response = client.post('/intervention/search', data=json.dumps(data), headers=make_headers(access_token)) 
    data = json.loads(response.data)['data']
    # TODO: Add consulta ao banco de dados e comparar count de intervenções

    assert response.status_code == 200

def test_get_interventions_by_reason(client):
    """Teste get /intervention/reasons - Compara quantidade de rasões enviadas com quantidade salva no banco e valida status_code 200"""
    
    access_token = get_access(client)
    qtdReasons = session.query(InterventionReason).count()
    
    response = client.get('/intervention/reasons', headers=make_headers(access_token))
    data = json.loads(response.data)['data']

    assert response.status_code == 200
    assert qtdReasons == len(data)

def test_put_interventions(client):
    """Teste put /intervention - Compara dados enviados com dados salvos no banco e valida status_code 200"""

    access_token = get_access(client, roles = [] )

    idPrescriptionDrug = '99'
    data = {
        "status": "s",
        "admissionNumber": 5,
        "idInterventionReason": [5],
        "error": False,
        "cost": False,
        "observation": "teste observations",
        "interactions": [5]
    }
    url = 'intervention/' + idPrescriptionDrug
    
    response = client.put(url, data=json.dumps(data), headers=make_headers(access_token))
    responseData = json.loads(response.data)['data']
    interventions = session.query(Intervention).get((responseData, '0'))
    
    assert response.status_code == 200
    assert interventions.status == data['status']
    assert interventions.admissionNumber == data['admissionNumber']
    assert interventions.idInterventionReason == data['idInterventionReason']
    assert interventions.error == data['error']
    assert interventions.cost == data['cost']
    assert interventions.notes == data['observation']
    assert interventions.interactions == data['interactions']

def test_put_interventions_permission(client):
    """Teste put /intervention - Deve retornar erro [401 UNAUTHORIZED] devido ao usuário utilizado"""

    access_token = get_access(client, roles = ["suporte"])

    idPrescriptionDrug = '20'
    data = {
        "status": "s",
        "admissionNumber": "5"  
    }
    url = 'intervention/' + idPrescriptionDrug
    
    response = client.put(url, data=json.dumps(data), headers=make_headers(access_token))
    
    assert response.status_code == 401
    



    