from conftest import *

def test_get_drugs(client):
    """Teste get /drugs/ - Valida status_code 200"""
    access_token = get_access(client)

    response = client.get('/drugs', headers=make_headers(access_token))
    data = json.loads(response.data)
    # TODO: Add consulta ao banco de dados e comparar retorno (retornando status 200 porém data = [])

    assert response.status_code == 200

def test_get_drugs_by_idSegment(client):
    """Teste get /drugs/idSegment - Valida status_code 200"""
    access_token = get_access(client)

    id = '5'

    response = client.get('/drugs/' + id, headers=make_headers(access_token))
    data = json.loads(response.data)    
    # TODO: Add consulta ao banco de dados e comparar retorno (retornando status 200 porém data = [])

    assert response.status_code == 200

def test_get_drugs_units_by_id(client):
    """Teste get /drugs/id/units - Valida status_code 200"""

    access_token = get_access(client)

    id = '10'

    response = client.get('/drugs/' + id + '/units', headers=make_headers(access_token))
    data = json.loads(response.data)
    # TODO: Add consulta ao banco de dados e comparar retorno (retornando status 200 porém data = [])

    assert response.status_code == 200

def test_get_substance(client):
    """Teste get /substance - Valida status_code 200"""

    access_token = get_access(client)

    response = client.get('/substance', headers=make_headers(access_token))
    data = json.loads(response.data)
    # TODO: Add consulta ao banco de dados e comparar retorno (retornando status 200 porém data = [])

    assert response.status_code == 200

def test_get_outliers_by_segment_and_drug(client):
    """Teste get /outliers/idSegment/idDrug - Valida status_code 200"""

    access_token = get_access(client)

    idSegment = 1
    idDrug = 5

    url = 'outliers/{0}/{1}'.format(idSegment, idDrug)

    response = client.get(url, headers=make_headers(access_token))
    data = json.loads(response.data)
    # TODO: Add consulta ao banco de dados e comparar retorno (necessário melhor compreensão dos dados retornados)

    assert response.status_code == 200