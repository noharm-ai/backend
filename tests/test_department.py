from conftest import *
from models.appendix import Department

def test_get_departments(client):
    """Teste get /departments/ - Compara quantidade de departments enviados com dados do banco e valida status_code 200"""
    access_token = get_access(client)

    qtdDepartment = session.query(Department).count()

    response = client.get('/departments', headers=make_headers(access_token))
    data = json.loads(response.data)['data']
    assert response.status_code == 200
    assert len(data) == qtdDepartment

def test_get_departments_free(client):
    """Teste get /departments/free - Valida status_code 200"""
    access_token = get_access(client)

    response = client.get('/departments/free', headers=make_headers(access_token))
    data = json.loads(response.data)
    # TODO: Add consulta ao banco de dados e comparar retorno (Compreender retorno para realizar comparação)
    assert response.status_code == 200