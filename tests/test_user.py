from sqlalchemy import or_
from conftest import *
from models.main import User

from routes.utils import tryCommit


def delete_user(email):
    user = session.query(User).filter(User.email == email).first()
    if user:
        session.delete(user)
        session_commit()


def create_user(client, data, access_token):
    delete_user(data["email"])

    return client.put(
        "/editUser", data=json.dumps(data), headers=make_headers(access_token)
    )


def test_get_users(client):
    """Teste get /users/ - Compara quantidade de usuários enviados com dados do banco e valida status_code 200"""
    access_token = get_access(client, roles=["userAdmin", "staging"])

    response = client.get("/users", headers=make_headers(access_token))
    data = json.loads(response.data)
    qtdUsers = (
        session.query(User)
        .filter(User.schema == "demo")
        .filter(
            or_(
                ~User.config["roles"].astext.contains("suporte"),
                User.config["roles"] == None,
            )
        )
        .count()
    )

    assert response.status_code == 200
    assert len(data["data"]) == qtdUsers


def test_get_users_permission(client):
    """Teste get /users/ - Deve retornar erro [401 UNAUTHORIZED] devido ao usuário utilizado"""
    access_token = get_access(client, "demo", "demo")

    response = client.get("/users", headers=make_headers(access_token))

    assert response.status_code == 401


def test_put_user(client):
    """Teste put /editUser - Compara o response.data e cria o usuário"""
    access_token = get_access(client, roles=["userAdmin", "staging"])

    data = {
        "id": "",
        "email": "test@noharm.ai",
        "name": "test3",
        "external": "test",
        "active": "true",
    }

    response = create_user(client, data, access_token)
    responseObject = json.loads(response.data)
    userId = responseObject["data"]
    user = session.query(User).filter(User.id == userId).first()

    assert response.status_code == 200
    assert userId == user.id


def test_put_editUser(client):
    """Teste put /editUser/<int:idUser> - Compara o response.data e edita o usuário"""
    access_token = get_access(client, roles=["userAdmin", "staging"])

    # first insert user
    create_data = {
        "id": "",
        "email": "test@noharm.ai",
        "name": "test3",
        "external": "test",
        "active": "true",
    }

    response = create_user(client, create_data, access_token)
    assert response.status_code == 200

    user = session.query(User).filter(User.email == create_data["email"]).first()
    assert user != None

    data = {
        "id": user.id,
        "email": user.email,
        "name": "updateTest",
        "external": "updateTest",
        "active": False,
    }

    response = client.put(
        "/editUser/" + str(user.id),
        data=json.dumps(data),
        headers=make_headers(access_token),
    )
    assert response.status_code == 200

    session_commit()

    userEdited = session.query(User).filter(User.id == user.id).first()

    assert data["name"] == userEdited.name
    assert data["external"] == userEdited.external
    assert data["active"] == userEdited.active


def test_create_user_invalid_role(client):
    """Teste put /editUser - Verifica roles criadas"""
    access_token = get_access(client, roles=["userAdmin", "staging"])
    email = "test3@noharm.ai"

    delete_user(email)

    data = {
        "id": "",
        "email": email,
        "name": "test3",
        "external": "test",
        "active": "true",
        "roles": ["admin"],
    }

    response = client.put(
        "/editUser", data=json.dumps(data), headers=make_headers(access_token)
    )
    responseObject = json.loads(response.data)
    userId = responseObject["data"]
    user = session.query(User).filter(User.id == userId).first()

    assert response.status_code == 200
    assert "admin" not in user.config["roles"]
    assert "userAdmin" not in user.config["roles"]


def test_update_user_invalid_role(client):
    """Teste put /editUser/<int:idUser> - Compara o response.data e edita o usuário"""
    access_token = get_access(client, roles=["userAdmin", "staging"])

    # first insert user
    create_data = {
        "id": "",
        "email": "test4@noharm.ai",
        "name": "test3",
        "external": "test",
        "active": "true",
    }

    response = create_user(client, create_data, access_token)
    assert response.status_code == 200

    user = session.query(User).filter(User.email == create_data["email"]).first()
    assert user != None

    data = {
        "id": user.id,
        "email": user.email,
        "name": "updateTest",
        "external": "updateTest",
        "active": False,
        "roles": ["admin"],
    }

    response = client.put(
        "/editUser/" + str(user.id),
        data=json.dumps(data),
        headers=make_headers(access_token),
    )
    assert response.status_code == 200

    session_commit()

    userEdited = session.query(User).filter(User.id == user.id).first()

    assert data["name"] == userEdited.name
    assert data["external"] == userEdited.external
    assert "admin" not in user.config["roles"]
    assert "userAdmin" not in user.config["roles"]


def test_create_user_invalid_role_perimission(client):
    """Teste put /editUser - Roles inválidas"""

    email = "test5@noharm.ai"

    delete_user(email)

    data = {
        "id": "",
        "email": email,
        "name": "test3",
        "external": "test",
        "active": "true",
        "roles": ["admin"],
    }

    access_token = get_access(client, roles=["userAdmin", "staging", "admin"])
    response = client.put(
        "/editUser", data=json.dumps(data), headers=make_headers(access_token)
    )
    assert response.status_code == 401

    access_token = get_access(client, roles=["userAdmin", "staging", "training"])
    response = client.put(
        "/editUser", data=json.dumps(data), headers=make_headers(access_token)
    )
    assert response.status_code == 401


def test_update_user_invalid_role_permission(client):
    """Teste put /editUser/<int:idUser> - Edição com roles inválidas"""
    access_token = get_access(client, roles=["userAdmin", "staging"])

    # first insert user
    create_data = {
        "id": "",
        "email": "test6@noharm.ai",
        "name": "test3",
        "external": "test",
        "active": "true",
    }

    response = create_user(client, create_data, access_token)
    assert response.status_code == 200

    user = session.query(User).filter(User.email == create_data["email"]).first()
    assert user != None

    data = {
        "id": user.id,
        "email": user.email,
        "name": "updateTest",
        "external": "updateTest",
        "active": False,
        "roles": ["admin"],
    }

    access_token = get_access(client, roles=["userAdmin", "staging", "admin"])
    response = client.put(
        "/editUser/" + str(user.id),
        data=json.dumps(data),
        headers=make_headers(access_token),
    )
    assert response.status_code == 401

    access_token = get_access(client, roles=["userAdmin", "staging", "training"])
    response = client.put(
        "/editUser/" + str(user.id),
        data=json.dumps(data),
        headers=make_headers(access_token),
    )
    assert response.status_code == 401
