from conftest import *

from models.appendix import InterventionReason
from models.prescription import Intervention

@pytest.mark.skip(reason="WIP")
def test_get_interventions(client):
    """Teste get /intervention - Compara quantidade de intervenções enviadas com quantidade salva no banco e valida status_code 200"""
    
    access_token = get_access(client)
    interventions = session.query(Intervention).all()

    response = client.get('/intervention', headers=make_headers(access_token)) 
    # TODO: Add consulta ao banco de dados e comparar count de intervenções
    data = json.loads(response.data) # Está retornando []

    # breakpoint()

    assert response.status_code == 200

def test_get_interventions_by_reason(client):
    """Teste get /intervention/reasons - Compara quantidade de rasões enviadas com quantidade salva no banco e valida status_code 200"""
    
    access_token = get_access(client)
    reasons = session.query(InterventionReason).all()
    
    response = client.get('/intervention/reasons', headers=make_headers(access_token))
    data = json.loads(response.data)['data']

    assert response.status_code == 200
    assert len(reasons) == len(data)

@pytest.mark.skip(reason="WIP")
def test_put_interventions(client):
    """Teste put /intervention - Compara dados enviados com dados salvos no banco e valida status_code 200"""

    access_token = get_access(client, 'noadmin', 'noadmin')

    idPrescriptionDrug = '20'
    mimetype = 'application/json'
    authorization = 'Bearer {}'.format(access_token)
    headers = {
        'Content-Type': mimetype,
        'Accept': mimetype,
        'Authorization': authorization
    }
    data = {
        "status": "s",
        "admissionNumber": "5"
    }
    url = 'intervention/' + idPrescriptionDrug
    
    response = client.put(url, data=json.dumps(data), headers=headers)
    data = json.loads(response.data)['data']
    # TODO: Add consulta ao banco de dados para comparar dados das intervenções
    # TODO: Add compreender retorno do put
    breakpoint()
    assert response.status_code == 200



def test_put_interventions_permission(client):
    """Teste put /intervention - Deve retornar erro [401 UNAUTHORIZED] devido ao usuário utilizado"""

    access_token = get_access(client)

    idPrescriptionDrug = '20'
    mimetype = 'application/json'
    authorization = 'Bearer {}'.format(access_token)
    headers = {
        'Content-Type': mimetype,
        'Accept': mimetype,
        'Authorization': authorization
    }
    data = {
        "status": "s",
        "admissionNumber": "5"  
    }
    url = 'intervention/' + idPrescriptionDrug
    
    response = client.put(url, data=json.dumps(data), headers=headers)
    assert response.status_code == 401


    