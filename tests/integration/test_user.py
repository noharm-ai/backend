from tests.conftest import session, session_commit

from models.main import User
from security.role import Role


def _delete_user(email):
    user = session.query(User).filter(User.email == email).first()
    if user:
        session.delete(user)
        session_commit()


def _create_user(client, data, headers):
    _delete_user(data["email"])
    return client.post("/editUser", json=data, headers=headers)


def test_get_users(client, user_manager_headers):
    """Teste get /users/ - Compara quantidade de usuários enviados com dados do banco e valida status_code 200"""
    response = client.get("/users", headers=user_manager_headers)

    assert response.status_code == 200


def test_get_users_permission(client, analyst_headers):
    """Teste get /users/ - Deve retornar erro [401 UNAUTHORIZED] devido ao usuário utilizado"""
    response = client.get("/users", headers=analyst_headers)

    assert response.status_code == 401


def test_put_user(client, user_manager_headers):
    """Teste put /editUser - Compara o response.data e cria o usuário"""
    data = {
        "email": "test@noharm.ai",
        "name": "test3",
        "external": "test",
        "active": "true",
        "roles": [Role.PRESCRIPTION_ANALYST.value],
    }

    response = _create_user(client, data, user_manager_headers)
    user_id = response.get_json()["data"]["id"]
    user = session.query(User).filter(User.id == user_id).first()

    assert response.status_code == 200
    assert user_id == user.id


def test_put_editUser(client, user_manager_headers):
    """Teste put /editUser/<int:idUser> - Compara o response.data e edita o usuário"""
    create_data = {
        "email": "test@noharm.ai",
        "name": "test3",
        "external": "test",
        "active": "true",
        "roles": [Role.PRESCRIPTION_ANALYST.value],
    }

    response = _create_user(client, create_data, user_manager_headers)
    assert response.status_code == 200

    user = session.query(User).filter(User.email == create_data["email"]).first()
    assert user is not None

    data = {
        "id": user.id,
        "email": user.email,
        "name": "updateTest",
        "external": "updateTest",
        "active": False,
        "roles": [Role.PRESCRIPTION_ANALYST.value],
    }

    response = client.post("/editUser", json=data, headers=user_manager_headers)
    assert response.status_code == 200

    session_commit()

    user_edited = session.query(User).filter(User.id == user.id).first()
    assert data["name"] == user_edited.name
    assert data["external"] == user_edited.external
    assert data["active"] == user_edited.active


def test_create_user_check_roles(client, user_manager_headers):
    """Teste put /editUser - Verifica roles criadas"""
    email = "test3@noharm.ai"
    _delete_user(email)

    data = {
        "email": email,
        "name": "test3",
        "external": "test",
        "active": "true",
        "roles": [Role.PRESCRIPTION_ANALYST.value],
    }

    response = client.post("/editUser", json=data, headers=user_manager_headers)
    user_id = response.get_json()["data"]["id"]
    user = session.query(User).filter(User.id == user_id).first()

    assert response.status_code == 200
    assert Role.ADMIN.value not in user.config["roles"]
    assert Role.CURATOR.value not in user.config["roles"]
    assert Role.USER_MANAGER.value not in user.config["roles"]
    assert Role.PRESCRIPTION_ANALYST.value in user.config["roles"]


def test_update_user_invalid_role(client, user_manager_headers):
    """Teste put /editUser/<int:idUser> - Compara o response.data e edita o usuário"""
    create_data = {
        "email": "test4@noharm.ai",
        "name": "test3",
        "external": "test",
        "active": "true",
        "roles": [Role.PRESCRIPTION_ANALYST.value],
    }

    response = _create_user(client, create_data, user_manager_headers)
    assert response.status_code == 200

    user = session.query(User).filter(User.email == create_data["email"]).first()
    assert user is not None

    data = {
        "id": user.id,
        "email": user.email,
        "name": "updateTest",
        "external": "updateTest",
        "active": False,
        "roles": [Role.DISCHARGE_MANAGER.value],
    }

    response = client.post("/editUser", json=data, headers=user_manager_headers)
    assert response.status_code == 200

    session_commit()

    user_edited = session.query(User).filter(User.id == user.id).first()
    assert data["name"] == user_edited.name
    assert data["external"] == user_edited.external
    assert Role.ADMIN.value not in user.config["roles"]
    assert Role.DISCHARGE_MANAGER.value in user.config["roles"]


def test_create_user_invalid_role_perimission(client, user_manager_headers):
    """Teste put /editUser - Roles inválidas"""
    email = "test5@noharm.ai"
    _delete_user(email)

    data = {
        "email": email,
        "name": "test3",
        "external": "test",
        "active": "true",
        "roles": [Role.ADMIN.value],
    }

    response = client.post("/editUser", json=data, headers=user_manager_headers)
    assert response.status_code == 400


def test_update_user_invalid_role_permission(client, user_manager_headers):
    """Teste put /editUser/<int:idUser> - Edição com roles inválidas"""
    create_data = {
        "email": "test6@noharm.ai",
        "name": "test3",
        "external": "test",
        "active": "true",
        "roles": [Role.PRESCRIPTION_ANALYST.value],
    }

    response = _create_user(client, create_data, user_manager_headers)
    assert response.status_code == 200

    user = session.query(User).filter(User.email == create_data["email"]).first()
    assert user is not None

    data = {
        "id": user.id,
        "email": user.email,
        "name": "updateTest",
        "external": "updateTest",
        "active": False,
        "roles": [Role.CURATOR.value],
    }

    response = client.post("/editUser", json=data, headers=user_manager_headers)
    assert response.status_code == 400


def test_create_user_invalid_authorization(client, user_manager_headers):
    """Teste put /editUser - Verifica autorizacao de segmento"""
    email = "test3@noharm.ai"
    _delete_user(email)

    data = {
        "email": email,
        "name": "test3",
        "external": "test",
        "active": "true",
        "roles": [Role.PRESCRIPTION_ANALYST.value],
        "segments": [3],
    }

    response = client.post("/editUser", json=data, headers=user_manager_headers)
    assert response.status_code == 401


def test_update_user_authorization(client, user_manager_headers):
    """Teste put /editUser/<int:idUser> - Testa permissao de ediçao de autorizacoes"""
    email = "test7@noharm.ai"
    _delete_user(email)

    create_data = {
        "email": email,
        "name": "test3",
        "external": "test",
        "active": "true",
        "roles": [Role.PRESCRIPTION_ANALYST.value],
    }

    response = _create_user(client, create_data, user_manager_headers)
    assert response.status_code == 200

    user = session.query(User).filter(User.email == create_data["email"]).first()
    assert user is not None

    data = {
        "id": user.id,
        "email": user.email,
        "name": "updateTest",
        "external": "updateTest",
        "active": False,
        "roles": [Role.PRESCRIPTION_ANALYST.value],
        "segments": [3],
    }

    # invalid authorization
    response = client.post("/editUser", json=data, headers=user_manager_headers)
    assert response.status_code == 401

    # valid authorization
    data["segments"] = [1]
    response = client.post("/editUser", json=data, headers=user_manager_headers)
    assert response.status_code == 200
