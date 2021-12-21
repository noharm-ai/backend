from flask.wrappers import Response
from sqlalchemy.sql.functions import user
from conftest import *
from models.main import User
import time

from routes.utils import tryCommit

def delete_user(email):
    user = session.query(User).filter(User.email == email).first()
    if user:
        session.delete(user)
        session_commit()

def test_get_reports(client):
    """Teste get /reports/ - Valida status_code 200"""
    access_token = get_access(client)

    response = client.get('/reports', headers=make_headers(access_token))
    data = json.loads(response.data)
    # TODO: Add consulta ao banco de dados e comparar retorno (retornando status 200 porém data = [])

    assert response.status_code == 200

def test_get_users(client):
    """Teste get /users/ - Compara quantidade de usuários enviados com dados do banco e valida status_code 200"""
    access_token = get_access(client, roles=["userAdmin"])

    response = client.get('/users', headers=make_headers(access_token))
    data = json.loads(response.data)
    qtdUsers = session.query(User).filter(User.schema == "demo").count()

    assert response.status_code == 200
    assert len(data["data"]) == qtdUsers
    
def test_get_users_permission(client):
    """Teste get /users/ - Deve retornar erro [401 UNAUTHORIZED] devido ao usuário utilizado"""
    access_token = get_access(client, 'demo', 'demo')

    response = client.get('/users', headers=make_headers(access_token))

    assert response.status_code == 401

def test_put_user(client):
    """Teste put /editUser - Compara o response.data e cria o usuário """
    access_token = get_access(client, roles = ["userAdmin"] )

    data = {
        "id": "",
        "email": "test@noharm.ai",
        "name": "test3",
        "external": "test",
        "active": "true"
    }

    response = client.put('/editUser', data=json.dumps(data), headers=make_headers(access_token))
    responseObject = json.loads(response.data)
    userId = responseObject["data"]
    user = session.query(User).filter(User.id == userId).first()

    assert response.status_code == 200
    assert userId == user.id

def test_put_editUser(client):
    """Teste put /editUser/<int:idUser> - Compara o response.data e edita o usuário """
    access_token = get_access(client, roles = ["userAdmin"] )

    user = session.query(User).filter(User.email == "test@noharm.ai").first()
    assert user != None

    data = {
        "id": user.id,
        "email": user.email,
        "name": "updateTest",
        "external": "updateTest",
        "active": False
    }

    response = client.put('/editUser/' + str(user.id) , data=json.dumps(data), headers=make_headers(access_token))
    assert response.status_code == 200

    session_commit()

    userEdited = session.query(User).filter(User.id == user.id ).first() 
    print("OUTRA COISA", userEdited.name)

    assert data["name"] == userEdited.name
    assert data["external"] == userEdited.external
    assert data["active"] ==  userEdited.active

    delete_user("test@noharm.ai")