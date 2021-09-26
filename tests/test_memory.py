from conftest import *

def test_get_memory(client):
    """Teste get /drugs/ - Valida status_code 200"""
    access_token = get_access(client)

    response = client.get('/memory/drugs', headers=make_headers(access_token))
    data = json.loads(response.data)
    # TODO: Add consulta ao banco de dados e comparar retorno (retornando status 200 porém data = [])

    assert response.status_code == 200
    assert data['data'] == []