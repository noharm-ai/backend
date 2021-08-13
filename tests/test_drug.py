from conftest import *

def test_get_drugs(client):
    """Teste get /drugs/ - Valida status_code 200"""
    access_token = get_access(client)

    response = client.get('/drugs', headers=make_headers(access_token))
    data = json.loads(response.data)
    # TODO: Add consulta ao banco de dados e comparar retorno (retornando status 200 porém data = [])

    assert response.status_code == 200

def test_get_drugs_by_id(client):
    """Teste get /drugs/id - Valida status_code 200"""
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
