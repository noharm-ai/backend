"""Integration tests for the business rules of the user upsert (POST /user-admin/upsert).

``tests/integration/test_user.py`` covers the happy paths, email format and role
validation. These tests cover the remaining rules enforced by
``user_admin_service.upsert_user``:

* when the schema has return integration enabled, the external id is required —
  except for a MAINTAINER;
* an email can only be used by one user;
* a user must keep at least one role, on create and on update;
* only ADMIN_USERS holders may assign features, and only from the allowlist;
* an update must target an existing user of the responsible's own schema.

Users created here use the ``test%@example.com`` pattern removed by
``_cleanup`` in ``tests/conftest.py``; each test also removes its own rows.
"""

import json

import pytest
from sqlalchemy import text

from models.enums import FeatureEnum
from models.main import User
from security.role import Role
from tests.conftest import session, session_commit

UPSERT_URL = "/user-admin/upsert"
EMAIL = "test_upsert_rules@example.com"
OTHER_SCHEMA_EMAIL = "test_upsert_other_schema@example.com"


def _delete_user(email: str):
    """Remove a user (and its authorizations) created by these tests."""
    session.execute(
        text(
            "DELETE FROM public.usuario_autorizacao WHERE idusuario IN "
            "(SELECT idusuario FROM public.usuario WHERE email = :email)"
        ),
        {"email": email},
    )
    session.execute(
        text("DELETE FROM public.usuario WHERE email = :email"), {"email": email}
    )
    session_commit()


def _payload(**overrides) -> dict:
    """Build a valid create payload, overriding the given fields."""
    data = {
        "email": EMAIL,
        "name": "Fulano Beltrano",
        "external": "EXT-TEST-1",
        "active": True,
        "roles": [Role.PRESCRIPTION_ANALYST.value],
    }
    data.update(overrides)
    return data


def _get_user(email: str = EMAIL) -> User:
    """Load a user by email straight from the database."""
    session_commit()
    return session.query(User).filter(User.email == email).first()


@pytest.fixture
def clean_user():
    """Make sure the test user does not exist before and after each test."""
    _delete_user(EMAIL)
    yield
    _delete_user(EMAIL)


@pytest.fixture
def created_user(client, user_manager_headers, clean_user):
    """Create the test user through the endpoint and return its id."""
    response = client.post(UPSERT_URL, json=_payload(), headers=user_manager_headers)
    assert response.status_code == 200

    return response.get_json()["data"]["id"]


@pytest.fixture
def return_integration():
    """Turn on return integration for the demo schema, restoring it afterwards."""
    previous = session.execute(
        text(
            "SELECT integracao_retorno FROM public.schema_config "
            "WHERE schema_name = 'demo'"
        )
    ).scalar()
    session.execute(
        text(
            "UPDATE public.schema_config SET integracao_retorno = true "
            "WHERE schema_name = 'demo'"
        )
    )
    session_commit()

    try:
        yield
    finally:
        session.execute(
            text(
                "UPDATE public.schema_config SET integracao_retorno = :previous "
                "WHERE schema_name = 'demo'"
            ),
            {"previous": previous},
        )
        session_commit()


@pytest.fixture
def other_schema_user():
    """A user that belongs to another schema."""
    _delete_user(OTHER_SCHEMA_EMAIL)
    user_id = session.execute(
        text(
            "INSERT INTO public.usuario (nome, email, senha, schema, config, ativo) "
            "VALUES ('Ciclano de Tal', :email, 'x', 'zz_other_schema', "
            "CAST(:config AS json), true) RETURNING idusuario"
        ),
        {
            "email": OTHER_SCHEMA_EMAIL,
            "config": json.dumps({"roles": [Role.VIEWER.value]}),
        },
    ).scalar()
    session_commit()

    try:
        yield user_id
    finally:
        _delete_user(OTHER_SCHEMA_EMAIL)


# --- return integration -------------------------------------------------------


def test_return_integration_requires_external_id(
    client, user_manager_headers, clean_user, return_integration
):
    """With return integration on, a user without external id is rejected."""
    response = client.post(
        UPSERT_URL, json=_payload(external="   "), headers=user_manager_headers
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == (
        "O campo ID Externo é de preenchimento obrigatório"
    )
    assert _get_user() is None


def test_return_integration_accepts_external_id(
    client, user_manager_headers, clean_user, return_integration
):
    """With return integration on, a user with external id is created (trimmed)."""
    response = client.post(
        UPSERT_URL, json=_payload(external="  EXT-1  "), headers=user_manager_headers
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["external"] == "EXT-1"


def test_return_integration_maintainer_may_skip_external_id(
    client, admin_headers, clean_user, return_integration
):
    """A MAINTAINER can create a user without external id even with return integration."""
    response = client.post(
        UPSERT_URL, json=_payload(external=None), headers=admin_headers
    )

    assert response.status_code == 200
    assert _get_user().external is None


# --- create -------------------------------------------------------------------


def test_create_rejects_duplicated_email(client, user_manager_headers, created_user):
    """An email already in use cannot be reused, regardless of case or spaces."""
    response = client.post(
        UPSERT_URL,
        json=_payload(email=f"  {EMAIL.upper()} "),
        headers=user_manager_headers,
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == "Já existe um usuário com este email"
    assert session.query(User).filter(User.email == EMAIL).count() == 1


def test_create_requires_at_least_one_role(client, user_manager_headers, clean_user):
    """A new user without roles is rejected."""
    response = client.post(
        UPSERT_URL, json=_payload(roles=[]), headers=user_manager_headers
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == (
        "O usuário deve ter ao menos um Papel definido"
    )
    assert _get_user() is None


def test_create_ignores_features_without_admin_users(
    client, user_manager_headers, clean_user
):
    """Features sent by a USER_MANAGER (no ADMIN_USERS) are not persisted."""
    response = client.post(
        UPSERT_URL,
        json=_payload(features=[FeatureEnum.STAGING_ACCESS.value]),
        headers=user_manager_headers,
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["features"] == []
    assert _get_user().config["features"] == []


def test_create_admin_users_assigns_features(client, admin_headers, clean_user):
    """An ADMIN_USERS holder can assign an allowed feature on create."""
    response = client.post(
        UPSERT_URL,
        json=_payload(features=[FeatureEnum.DISABLE_CPOE.value]),
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["features"] == [FeatureEnum.DISABLE_CPOE.value]


def test_create_rejects_feature_outside_allowlist(client, admin_headers, clean_user):
    """Even an ADMIN_USERS holder cannot assign a feature outside the allowlist."""
    response = client.post(
        UPSERT_URL,
        json=_payload(features=[FeatureEnum.OAUTH.value]),
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == "Feature inválida"
    assert _get_user() is None


# --- update -------------------------------------------------------------------


def test_update_unknown_user(client, user_manager_headers):
    """Updating an id that does not exist is rejected."""
    response = client.post(
        UPSERT_URL, json=_payload(id=999999999), headers=user_manager_headers
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == "Usuário inexistente"


def test_update_user_from_another_schema(
    client, user_manager_headers, other_schema_user
):
    """A user of another schema cannot be edited and stays unchanged."""
    response = client.post(
        UPSERT_URL,
        json=_payload(id=other_schema_user, email=OTHER_SCHEMA_EMAIL, name="Hacked"),
        headers=user_manager_headers,
    )

    assert response.status_code == 401
    assert response.get_json()["message"] == "Usuário não autorizado"
    assert _get_user(OTHER_SCHEMA_EMAIL).name == "Ciclano de Tal"


def test_update_requires_at_least_one_role(client, user_manager_headers, created_user):
    """Removing every role from an existing user is rejected."""
    response = client.post(
        UPSERT_URL,
        json=_payload(id=created_user, roles=[]),
        headers=user_manager_headers,
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == (
        "O usuário deve ter ao menos um Papel definido"
    )
    assert _get_user().config["roles"] == [Role.PRESCRIPTION_ANALYST.value]


def test_update_legacy_roles_only_counts_as_no_role(
    client, user_manager_headers, created_user
):
    """Legacy roles are dropped before validation, so they do not count as a role."""
    response = client.post(
        UPSERT_URL,
        json=_payload(id=created_user, roles=["suporte", "readonly"]),
        headers=user_manager_headers,
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == (
        "O usuário deve ter ao menos um Papel definido"
    )


def test_update_keeps_features_without_admin_users(
    client, admin_headers, user_manager_headers, created_user
):
    """A USER_MANAGER update keeps the features previously set by an admin."""
    response = client.post(
        UPSERT_URL,
        json=_payload(id=created_user, features=[FeatureEnum.DISABLE_CPOE.value]),
        headers=admin_headers,
    )
    assert response.status_code == 200

    response = client.post(
        UPSERT_URL,
        json=_payload(id=created_user, name="Maria Teste", features=[]),
        headers=user_manager_headers,
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["name"] == "Maria Teste"
    assert data["features"] == [FeatureEnum.DISABLE_CPOE.value]


def test_update_admin_users_rejects_feature_outside_allowlist(
    client, admin_headers, created_user
):
    """An admin update with a feature outside the allowlist is rejected."""
    response = client.post(
        UPSERT_URL,
        json=_payload(id=created_user, features=[FeatureEnum.OAUTH.value]),
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == "Feature inválida"
    assert _get_user().config["features"] == []
