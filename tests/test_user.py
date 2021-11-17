from conftest import *
from models.main import User

def test_get_reports(client):
    """Teste get /reports/ - Valida status_code 200"""
    access_token = get_access(client)

    response = client.get('/reports', headers=make_headers(access_token))
    data = json.loads(response.data)
    # TODO: Add consulta ao banco de dados e comparar retorno (retornando status 200 porém data = [])

    assert response.status_code == 200

def test_get_users(client):
    """Teste get /users/ - Compara quantidade de usuários enviados com dados do banco e valida status_code 200"""
    access_token = get_access(client)

    response = client.get('/users', headers=make_headers(access_token))
    data = json.loads(response.data)
    user = session.query(User).filter_by(email = 'noadmin')
    qtdUsers = session.query(User).filter(User.schema == user[0].schema).count()

    assert response.status_code == 200
    assert len(data) == qtdUsers
    
def test_get_users_permission(client):
    """Teste get /users/ - Deve retornar erro [401 UNAUTHORIZED] devido ao usuário utilizado"""
    access_token = get_access(client, 'demo', 'demo')

    response = client.get('/users', headers=make_headers(access_token))

    assert response.status_code == 401

#@pytest.mark.skip(reason="Pendente ajustes! (validar adição e remover usuário adicionado)")
def test_put_user(client):
    """Teste put /editUser - """

    access_token = get_access(client)

    data = {
        "id": "",
        "email": "teste3",
        "name": "teste3",
        "external": "teste",
        "active": "true"
    }
    
    response = client.put('/editUser', data=json.dumps(data), headers=make_headers(access_token))
    breakpoint()
    assert response.status_code == 200