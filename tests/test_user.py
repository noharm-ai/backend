import json

from conftest import session, session_commit, get_access, make_headers
from models.main import User
from security.role import Role


def delete_user(email):
    user = session.query(User).filter(User.email == email).first()
    if user:
        session.delete(user)
        session_commit()


def create_user(client, data, access_token):
    delete_user(data["email"])

    return client.post(
        "/editUser", data=json.dumps(data), headers=make_headers(access_token)
    )


def test_get_users(client):
    """Teste get /users/ - Compara quantidade de usuários enviados com dados do banco e valida status_code 200"""
    access_token = get_access(client, roles=[Role.USER_MANAGER.value])

    response = client.get("/users", headers=make_headers(access_token))

    assert response.status_code == 200


def test_get_users_permission(client):
    """Teste get /users/ - Deve retornar erro [401 UNAUTHORIZED] devido ao usuário utilizado"""
    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.get("/users", headers=make_headers(access_token))

    assert response.status_code == 401


def test_put_user(client):
    """Teste put /editUser - Compara o response.data e cria o usuário"""
    access_token = get_access(client, roles=[Role.USER_MANAGER.value])

    data = {
        "email": "test@noharm.ai",
        "name": "test3",
        "external": "test",
        "active": "true",
        "roles": [Role.PRESCRIPTION_ANALYST.value],
    }

    response = create_user(client, data, access_token)
    responseObject = json.loads(response.data)
    userId = responseObject["data"]["id"]
    user = session.query(User).filter(User.id == userId).first()

    assert response.status_code == 200
    assert userId == user.id


def test_put_editUser(client):
    """Teste put /editUser/<int:idUser> - Compara o response.data e edita o usuário"""
    access_token = get_access(client, roles=[Role.USER_MANAGER.value])

    # first insert user
    create_data = {
        "email": "test@noharm.ai",
        "name": "test3",
        "external": "test",
        "active": "true",
        "roles": [Role.PRESCRIPTION_ANALYST.value],
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
        "roles": [Role.PRESCRIPTION_ANALYST.value],
    }

    response = client.post(
        "/editUser",
        data=json.dumps(data),
        headers=make_headers(access_token),
    )
    assert response.status_code == 200

    session_commit()

    userEdited = session.query(User).filter(User.id == user.id).first()

    assert data["name"] == userEdited.name
    assert data["external"] == userEdited.external
    assert data["active"] == userEdited.active


def test_create_user_check_roles(client):
    """Teste put /editUser - Verifica roles criadas"""
    access_token = get_access(client, roles=[Role.USER_MANAGER.value])
    email = "test3@noharm.ai"

    delete_user(email)

    data = {
        "email": email,
        "name": "test3",
        "external": "test",
        "active": "true",
        "roles": [Role.PRESCRIPTION_ANALYST.value],
    }

    response = client.post(
        "/editUser", data=json.dumps(data), headers=make_headers(access_token)
    )
    responseObject = json.loads(response.data)
    userId = responseObject["data"]["id"]
    user = session.query(User).filter(User.id == userId).first()

    assert response.status_code == 200
    assert Role.ADMIN.value not in user.config["roles"]
    assert Role.CURATOR.value not in user.config["roles"]
    assert Role.USER_MANAGER.value not in user.config["roles"]
    assert Role.PRESCRIPTION_ANALYST.value in user.config["roles"]


def test_update_user_invalid_role(client):
    """Teste put /editUser/<int:idUser> - Compara o response.data e edita o usuário"""
    access_token = get_access(client, roles=[Role.USER_MANAGER.value])

    # first insert user
    create_data = {
        "email": "test4@noharm.ai",
        "name": "test3",
        "external": "test",
        "active": "true",
        "roles": [Role.PRESCRIPTION_ANALYST.value],
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
        "roles": [Role.DISCHARGE_MANAGER.value],
    }

    response = client.post(
        "/editUser",
        data=json.dumps(data),
        headers=make_headers(access_token),
    )
    assert response.status_code == 200

    session_commit()

    userEdited = session.query(User).filter(User.id == user.id).first()

    assert data["name"] == userEdited.name
    assert data["external"] == userEdited.external
    assert Role.ADMIN.value not in user.config["roles"]
    assert Role.DISCHARGE_MANAGER.value in user.config["roles"]


def test_create_user_invalid_role_perimission(client):
    """Teste put /editUser - Roles inválidas"""

    email = "test5@noharm.ai"

    delete_user(email)

    data = {
        "email": email,
        "name": "test3",
        "external": "test",
        "active": "true",
        "roles": [Role.ADMIN.value],
    }

    access_token = get_access(client, roles=[Role.USER_MANAGER.value])
    response = client.post(
        "/editUser", data=json.dumps(data), headers=make_headers(access_token)
    )
    assert response.status_code == 400


def test_update_user_invalid_role_permission(client):
    """Teste put /editUser/<int:idUser> - Edição com roles inválidas"""
    access_token = get_access(client, roles=[Role.USER_MANAGER.value])

    # first insert user
    create_data = {
        "email": "test6@noharm.ai",
        "name": "test3",
        "external": "test",
        "active": "true",
        "roles": [Role.PRESCRIPTION_ANALYST.value],
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
        "roles": [Role.CURATOR.value],
    }

    access_token = get_access(client, roles=[Role.USER_MANAGER.value])
    response = client.post(
        "/editUser",
        data=json.dumps(data),
        headers=make_headers(access_token),
    )
    assert response.status_code == 400


def test_create_user_invalid_authorization(client):
    """Teste put /editUser - Verifica autorizacao de segmento"""
    access_token = get_access(client, roles=[Role.USER_MANAGER.value])
    email = "test3@noharm.ai"

    delete_user(email)

    data = {
        "email": email,
        "name": "test3",
        "external": "test",
        "active": "true",
        "roles": [Role.PRESCRIPTION_ANALYST.value],
        "segments": [2],
    }

    response = client.post(
        "/editUser", data=json.dumps(data), headers=make_headers(access_token)
    )

    assert response.status_code == 401


def test_update_user_authorization(client):
    """Teste put /editUser/<int:idUser> - Testa permissao de ediçao de autorizacoes"""
    access_token = get_access(client, roles=[Role.USER_MANAGER.value])
    email = "test7@noharm.ai"

    delete_user(email)

    # first insert user
    create_data = {
        "email": email,
        "name": "test3",
        "external": "test",
        "active": "true",
        "roles": [Role.PRESCRIPTION_ANALYST.value],
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
        "roles": [Role.PRESCRIPTION_ANALYST.value],
        "segments": [2],
    }

    # invalida authorization
    response = client.post(
        "/editUser",
        data=json.dumps(data),
        headers=make_headers(access_token),
    )
    assert response.status_code == 401

    # valid authorization
    data["segments"] = [1]
    response = client.post(
        "/editUser",
        data=json.dumps(data),
        headers=make_headers(access_token),
    )
    assert response.status_code == 200
