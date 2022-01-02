from conftest import *
from models.segment import Segment

def test_get_segments(client):
    """Teste get /segments/ - Compara quantidade de segmentos enviados com dados do banco e valida status_code 200"""
    access_token = get_access(client)

    qtdSegment = session.query(Segment).count()

    response = client.get('/segments', headers=make_headers(access_token))
    data = json.loads(response.data)['data']
    # TODO: Add consulta ao banco de dados e comparar retorno 
    assert response.status_code == 200
    assert len(data) == qtdSegment

def test_get_segments_by_idSegment(client):
    """Teste get /segments/idSegment - Valida status_code 200"""
    access_token = get_access(client)
    
    idSegment = '1'
    
    response = client.get('/segments/' + idSegment, headers=make_headers(access_token))
    data = json.loads(response.data)
    # TODO: Add consulta ao banco de dados e comparar retorno (Compreender retorno para realizar comparação)
    assert response.status_code == 200

def test_get_segments_exams_types(client):
    """Teste get /segments/exams/types - Valida status_code 200"""
    access_token = get_access(client)

    response = client.get('/segments/exams/types', headers=make_headers(access_token))
    data = json.loads(response.data)
    # TODO: Add consulta ao banco de dados e comparar retorno (Compreender retorno para realizar comparação)
    assert response.status_code == 200

def test_get_segments_idSegment_outliers_generate_drug_by_drug(client):
    """Teste get /segments/idSegment/outliers/generate/drug/idDrug - Valida status_code 200"""

    access_token = get_access(client)

    idSegment = '1'
    idDrug = '5'

    url = '/segments/{0}/outliers/generate/drug/{1}'.format(idSegment, idDrug)

    response = client.get(url, headers=make_headers(access_token))
    data = json.loads(response.data)
    # TODO: Add consulta ao banco de dados e comparar retorno (retornando apenas status = success)

    assert response.status_code == 200
    