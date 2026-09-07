"""Integration tests for the token refresh feature (``POST /refresh-token``).

A login hands the frontend a short-lived access token plus a long-lived refresh
token, stored in a cookie scoped to this one route. When the access token
expires the frontend posts here to mint a new one without asking for credentials
again.

Refreshing is not a free pass: the endpoint re-checks the things that could have
changed since login — the user must still exist and still be active, and the
tenant's integration must not have been canceled (maintainers keep access to a
canceled tenant so they can still fix it). What it deliberately does *not* do is
re-read the user's roles: the new access token carries the claims minted at login
forward, so a role change only takes effect on the next full login.

Tokens are built with ``create_refresh_token`` rather than by logging in, which
is what lets these tests reach the branches a real login cannot produce — claims
with no schema, a schema that no longer exists, a user id that was since removed.
The route accepts the token from either a cookie or an ``Authorization`` header;
these tests use the header.
"""

import json

import pytest
from flask_jwt_extended import create_access_token, create_refresh_token, decode_token
from sqlalchemy import text

from models.enums import IntegrationStatusEnum
from mobile import app
from security.role import Role
from tests.conftest import make_headers, session, session_commit
from utils import status

_USER_ID = 99010
_USER_EMAIL = "testrefresh@example.com"

_INACTIVE_ID = 99011
_INACTIVE_EMAIL = "testrefreshinactive@example.com"

# an id no seeded or test user occupies
_UNKNOWN_USER_ID = 987654

_ANALYST_CONFIG = {"roles": [Role.PRESCRIPTION_ANALYST.value], "features": []}
_ADMIN_CONFIG = {"roles": [Role.ADMIN.value], "features": []}


def _upsert_user(id_user: int, email: str, active: bool = True) -> None:
    """Create (or reset) a test user. Password is irrelevant: no login happens here."""
    session.execute(
        text(
            "INSERT INTO public.usuario"
            "  (idusuario, nome, email, senha, schema, fkusuario, config, ativo)"
            " VALUES"
            "  (:id, :name, :email, public.crypt('IrrelevantPass1', public.gen_salt('bf', 8)),"
            "   'demo', :external, CAST(:config AS json), :active)"
            " ON CONFLICT (idusuario) DO UPDATE SET"
            "   email = EXCLUDED.email, ativo = EXCLUDED.ativo"
        ),
        {
            "id": id_user,
            "name": f"ZZTest Refresh {id_user}",
            "email": email,
            "external": str(id_user),
            "config": json.dumps(_ANALYST_CONFIG),
            "active": active,
        },
    )
    session_commit()


def _set_user_config(id_user: int, config: dict) -> None:
    """Replace a test user's stored roles/features."""
    session.execute(
        text("UPDATE public.usuario SET config = CAST(:config AS json) WHERE idusuario = :id"),
        {"id": id_user, "config": json.dumps(config)},
    )
    session_commit()


def _set_integration_status(schema: str, integration_status: int) -> None:
    """Set a tenant's integration status."""
    session.execute(
        text("UPDATE public.schema_config SET status = :status WHERE schema_name = :schema"),
        {"schema": schema, "status": integration_status},
    )
    session_commit()


def _refresh_token(id_user: int, claims: dict = None):
    """Mint a refresh token for a user, with claims a login would normally set."""
    if claims is None:
        claims = {"schema": "demo", "config": _ANALYST_CONFIG}

    with app.app_context():
        return create_refresh_token(identity=str(id_user), additional_claims=claims)


def _post_refresh(client, token):
    return client.post("/refresh-token", headers=make_headers(token))


def _claims_of(token: str) -> dict:
    """Decode a token this app issued, to inspect the claims it carries."""
    with app.app_context():
        return decode_token(token)


@pytest.fixture(scope="module", autouse=True)
def refresh_users(clean_test_artifacts):  # noqa: ARG001
    """Create the module's users, and restore the demo tenant's status afterwards."""
    original_status = session.execute(
        text("SELECT status FROM public.schema_config WHERE schema_name = 'demo'")
    ).scalar()

    _upsert_user(_USER_ID, _USER_EMAIL)
    _upsert_user(_INACTIVE_ID, _INACTIVE_EMAIL, active=False)

    yield

    _set_integration_status("demo", original_status)


@pytest.fixture
def active_integration():
    """Keep the demo tenant in a non-canceled state for a test that changes it."""
    yield
    _set_integration_status("demo", IntegrationStatusEnum.INTEGRATION.value)


# --- the happy path -------------------------------------------------------


def test_refresh_issues_a_new_access_token(client):
    """A valid refresh token buys a fresh access token"""
    response = _post_refresh(client, _refresh_token(_USER_ID))

    assert response.status_code == status.HTTP_200_OK

    access_token = json.loads(response.data)["access_token"]

    assert access_token
    assert _claims_of(access_token)["type"] == "access"


def test_refresh_carries_the_original_claims_forward(client):
    """The new access token keeps the identity, schema and config it was minted with"""
    response = _post_refresh(client, _refresh_token(_USER_ID))

    claims = _claims_of(json.loads(response.data)["access_token"])

    assert claims["sub"] == str(_USER_ID)
    assert claims["schema"] == "demo"
    assert claims["config"] == _ANALYST_CONFIG


def test_refresh_does_not_pick_up_a_role_change(client):
    """Roles come from the token, not the database — a change needs a new login

    This is what lets a session keep working after an admin edits the user, and
    equally what makes a permission revocation wait for the next login.
    """
    token = _refresh_token(_USER_ID)
    _set_user_config(_USER_ID, _ADMIN_CONFIG)

    try:
        claims = _claims_of(json.loads(_post_refresh(client, token).data)["access_token"])
        # still the analyst config the token carried, not the ADMIN row now in the db
        assert claims["config"] == _ANALYST_CONFIG
    finally:
        _set_user_config(_USER_ID, _ANALYST_CONFIG)


# --- token validation (handled before the service is reached) -------------


def test_refresh_requires_a_token(client):
    """The endpoint is not reachable anonymously"""
    assert client.post("/refresh-token").status_code == status.HTTP_401_UNAUTHORIZED


def test_refresh_rejects_a_tampered_token(client):
    """A token that fails signature verification is refused, not merely ignored"""
    token = _refresh_token(_USER_ID)
    tampered = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")

    response = _post_refresh(client, tampered)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert json.loads(response.data)["code"] == "INVALID_TOKEN"


def test_refresh_rejects_an_access_token(client):
    """An access token cannot be used to mint another one

    Access tokens are sent to every endpoint, so accepting one here would turn
    any leaked access token into an unlimited session.
    """
    with app.app_context():
        access_token = create_access_token(
            identity=str(_USER_ID),
            additional_claims={"schema": "demo", "config": _ANALYST_CONFIG},
        )

    response = _post_refresh(client, access_token)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert json.loads(response.data)["code"] == "INVALID_TOKEN"


# --- what the service re-checks ------------------------------------------


def test_refresh_requires_a_schema_in_the_claims(client):
    """A token with no tenant cannot be refreshed"""
    token = _refresh_token(_USER_ID, claims={"config": _ANALYST_CONFIG})

    response = _post_refresh(client, token)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Request inválido" in json.loads(response.data)["message"]


def test_refresh_rejects_a_deleted_user(client):
    """A token outliving its user is refused"""
    response = _post_refresh(client, _refresh_token(_UNKNOWN_USER_ID))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Usuário inválido" in json.loads(response.data)["message"]


def test_refresh_rejects_an_inactive_user(client):
    """Deactivating a user ends their session at the next refresh"""
    response = _post_refresh(client, _refresh_token(_INACTIVE_ID))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Usuário inativo" in json.loads(response.data)["message"]


def test_refresh_rejects_an_unknown_schema(client):
    """A tenant that is no longer configured has no integration status to check"""
    token = _refresh_token(
        _USER_ID, claims={"schema": "not_a_schema", "config": _ANALYST_CONFIG}
    )

    response = _post_refresh(client, token)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Schema inválido" in json.loads(response.data)["message"]


def test_refresh_is_refused_on_a_canceled_integration(client, active_integration):
    """Canceling a tenant ends its users' sessions at the next refresh"""
    _set_integration_status("demo", IntegrationStatusEnum.CANCELED.value)

    response = _post_refresh(client, _refresh_token(_USER_ID))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Usuário inválido" in json.loads(response.data)["message"]


def test_refresh_allows_a_maintainer_on_a_canceled_integration(
    client, active_integration
):
    """A maintainer keeps access to a canceled tenant so it can still be worked on

    The permission comes from the user's stored roles, not from the token, so
    this is the one check a role change does take effect on immediately.
    """
    _set_integration_status("demo", IntegrationStatusEnum.CANCELED.value)
    _set_user_config(_USER_ID, _ADMIN_CONFIG)

    try:
        response = _post_refresh(client, _refresh_token(_USER_ID))
        assert response.status_code == status.HTTP_200_OK
    finally:
        _set_user_config(_USER_ID, _ANALYST_CONFIG)


def test_refresh_succeeds_on_a_production_integration(client, active_integration):
    """Only the canceled status blocks a refresh"""
    _set_integration_status("demo", IntegrationStatusEnum.PRODUCTION.value)

    assert _post_refresh(client, _refresh_token(_USER_ID)).status_code == (
        status.HTTP_200_OK
    )
