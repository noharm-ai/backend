"""Integration tests for the schemas an organization grants.

``usuario_extra.config['organization']`` (written by the admin's Organizações
page) names the organization a ``ORGANIZATION_MANAGER`` manages. With
``allSchemas`` the user reaches every schema in ``public.organizacao_schema``
for that organization, resolved on each login, so a schema added to the
organization later needs no change on the user. Without it, only the fixed
``config['schemas']`` list counts, as before.

The seed ships ``Organização Demo`` with ``demo`` (Hospital Demo) and ``teste``
(Hospital Teste). The tests rewrite the ``organizationmanager`` grant and put
it back on the way out.
"""

import json

import pytest
from flask_jwt_extended import decode_token
from sqlalchemy import text

from models.appendix import Organization, OrganizationSchema
from mobile import app
from models.main import User
from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit
from utils import status

SWITCH_URL = "/switch-schema"
_ORG_MANAGER_EMAIL = "organizationmanager"
_ORG_NAME = "Organização Demo"
_NEW_SCHEMA = "zz_org_test_new"
_OUTSIDER_EMAIL = "org.outsider@example.com"


def _org_id() -> int:
    return session.query(Organization).filter(Organization.name == _ORG_NAME).one().id


def _user_id(email: str) -> int:
    return session.query(User).filter(User.email == email).one().id


def _set_extra(user_id: int, config: dict | None):
    session.execute(
        text("delete from public.usuario_extra where idusuario = :id"), {"id": user_id}
    )
    if config is not None:
        session.execute(
            text(
                "insert into public.usuario_extra (idusuario, config, created_at, created_by)"
                " values (:id, :config, now(), 0)"
            ),
            {"id": user_id, "config": json.dumps(config)},
        )
    session_commit()


@pytest.fixture
def org_grant(client):
    """Rewrites the seeded manager's usuario_extra; returns a login function"""
    user_id = _user_id(_ORG_MANAGER_EMAIL)
    saved = session.execute(
        text("select config from public.usuario_extra where idusuario = :id"),
        {"id": user_id},
    ).scalar()
    saved_user_config = (
        session.query(User).filter(User.id == user_id).one().config
    )

    def login(config: dict) -> dict:
        _set_extra(user_id, config)
        return make_headers(
            get_access(
                client,
                email=_ORG_MANAGER_EMAIL,
                password=_ORG_MANAGER_EMAIL,
                roles=[Role.VIEWER.value],
            )
        )

    yield login

    _set_extra(user_id, saved)
    user = session.query(User).filter(User.id == user_id).one()
    user.config = saved_user_config
    session_commit()


@pytest.fixture
def new_org_schema():
    """A schema added to the organization after the grant was written"""
    session.execute(
        text(
            "insert into public.schema_config (schema_name, created_at)"
            " values (:name, now())"
        ),
        {"name": _NEW_SCHEMA},
    )
    session.execute(
        text(
            "insert into public.organizacao_schema"
            " (schema_name, idorganizacao, nome, created_at, created_by)"
            " values (:name, :org, 'Hospital Novo', now(), 0)"
        ),
        {"name": _NEW_SCHEMA, "org": _org_id()},
    )
    session_commit()

    yield _NEW_SCHEMA

    session.query(OrganizationSchema).filter(
        OrganizationSchema.schemaName == _NEW_SCHEMA
    ).delete()
    session.execute(
        text("delete from public.schema_config where schema_name = :name"),
        {"name": _NEW_SCHEMA},
    )
    session_commit()


def _all_schemas_grant() -> dict:
    return {
        "roles": [Role.ORGANIZATION_MANAGER.value],
        "schemas": [],
        "organization": {"id": _org_id(), "allSchemas": True},
    }


def test_all_schemas_lists_the_organization(client, org_grant):
    """The picker shows the organization's schemas with their friendly names"""
    headers = org_grant(_all_schemas_grant())

    response = client.get(SWITCH_URL, headers=headers)

    assert response.status_code == status.HTTP_200_OK
    data = response.get_json()["data"]
    assert data["maintainer"] is False
    assert data["schemas"] == [
        {"name": "demo", "friendlyName": "Hospital Demo"},
        {"name": "teste", "friendlyName": "Hospital Teste"},
    ]


def test_all_schemas_switches_into_the_organization(client, org_grant):
    headers = org_grant(_all_schemas_grant())

    response = client.post(SWITCH_URL, json={"schema": "teste"}, headers=headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["schema"] == "teste"


def _refresh_cookie(response) -> str:
    """The refresh token the response set as a cookie (the login keeps it out of
    the body)"""
    for header in response.headers.getlist("Set-Cookie"):
        name, _, rest = header.partition("=")
        if name == "refresh_token_cookie":
            return rest.split(";", 1)[0]
    raise AssertionError("no refresh_token_cookie set")


def test_the_schemas_stay_out_of_the_tokens(client, org_grant):
    """Login and switch tokens carry the config without the schema list: an
    organization's list would outgrow the refresh cookie, and the picker and the
    switch reload it from the database anyway"""
    headers = org_grant(_all_schemas_grant())

    login = client.post(
        "/authenticate",
        json={"email": _ORG_MANAGER_EMAIL, "password": _ORG_MANAGER_EMAIL},
    )
    switch = client.post(SWITCH_URL, json={"schema": "teste"}, headers=headers)
    assert switch.status_code == status.HTTP_200_OK

    tokens = [login.get_json()["access_token"], _refresh_cookie(login)]
    tokens += [switch.get_json()["data"]["access_token"], _refresh_cookie(switch)]
    with app.app_context():
        for token in tokens:
            config = decode_token(token)["config"]
            assert "schemas" not in config
            assert Role.ORGANIZATION_MANAGER.value in config["roles"]


def test_all_schemas_reaches_a_schema_added_later(client, org_grant, new_org_schema):
    """No change on the user: the next login already sees the new schema"""
    headers = org_grant(_all_schemas_grant())

    response = client.get(SWITCH_URL, headers=headers)

    names = [s["name"] for s in response.get_json()["data"]["schemas"]]
    assert new_org_schema in names


def test_all_schemas_refuses_a_schema_outside_the_organization(client, org_grant):
    """Only the organization's schemas: a configured schema elsewhere is refused"""
    session.execute(
        text("delete from public.organizacao_schema where schema_name = 'teste'")
    )
    session_commit()
    try:
        headers = org_grant(_all_schemas_grant())
        response = client.post(SWITCH_URL, json={"schema": "teste"}, headers=headers)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    finally:
        session.execute(
            text(
                "insert into public.organizacao_schema"
                " (schema_name, idorganizacao, nome, created_at, created_by)"
                " values ('teste', :org, 'Hospital Teste', now(), 0)"
            ),
            {"org": _org_id()},
        )
        session_commit()


def test_fixed_list_ignores_the_rest_of_the_organization(client, org_grant):
    """Without allSchemas only config['schemas'] counts"""
    headers = org_grant(
        {
            "roles": [Role.ORGANIZATION_MANAGER.value],
            "schemas": [{"name": "demo", "friendlyName": "Hospital Demo"}],
            "organization": {"id": _org_id(), "allSchemas": False},
        }
    )

    picker = client.get(SWITCH_URL, headers=headers).get_json()["data"]["schemas"]
    assert [s["name"] for s in picker] == ["demo"]

    response = client.post(SWITCH_URL, json={"schema": "teste"}, headers=headers)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_a_malformed_organization_grants_nothing_extra(client, org_grant):
    headers = org_grant(
        {
            "roles": [Role.ORGANIZATION_MANAGER.value],
            "schemas": [],
            "organization": {"id": str(_org_id()), "allSchemas": True},
        }
    )

    response = client.get(SWITCH_URL, headers=headers)

    assert response.get_json()["data"]["schemas"] == []


def test_the_organization_needs_the_manager_role(client, org_grant):
    """A NAVIGATOR (or a former manager) with an organization left in its config
    keeps only the fixed list"""
    headers = org_grant(dict(_all_schemas_grant(), roles=[Role.NAVIGATOR.value]))

    picker = client.get(SWITCH_URL, headers=headers).get_json()["data"]["schemas"]
    assert picker == []

    response = client.post(SWITCH_URL, json={"schema": "teste"}, headers=headers)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.fixture
def outsider():
    """A user of the ``teste`` schema, to be listed in ``demo``'s user list"""
    session.execute(
        text(
            "insert into public.usuario (nome, email, senha, schema, config)"
            " values ('Fulano Beltrano', :email, 'x', 'teste', '{\"roles\": []}')"
        ),
        {"email": _OUTSIDER_EMAIL},
    )
    session_commit()
    user_id = _user_id(_OUTSIDER_EMAIL)

    yield user_id

    _set_extra(user_id, None)
    session.execute(
        text("delete from public.usuario where idusuario = :id"), {"id": user_id}
    )
    session_commit()


@pytest.mark.parametrize(
    "role, all_schemas, id_as_text, listed",
    [
        (Role.ORGANIZATION_MANAGER, True, False, True),
        (Role.ORGANIZATION_MANAGER, False, False, False),
        # same rules as the login: no role or a malformed id grants nothing
        (Role.NAVIGATOR, True, False, False),
        (Role.ORGANIZATION_MANAGER, True, True, False),
    ],
)
def test_users_list_shows_organization_managers(
    client, admin_headers, outsider, role, all_schemas, id_as_text, listed
):
    """A maintainer sees, read-only, who reaches this schema through the
    organization, as it does for the fixed list"""
    org_id = str(_org_id()) if id_as_text else _org_id()
    _set_extra(
        outsider,
        {
            "roles": [role.value],
            "schemas": [],
            "organization": {"id": org_id, "allSchemas": all_schemas},
        },
    )

    response = client.get("/users", headers=admin_headers)

    assert response.status_code == status.HTTP_200_OK
    rows = {u["id"]: u for u in response.get_json()["data"]}
    assert (outsider in rows) is listed
    if listed:
        assert rows[outsider]["readOnly"] is True
        assert rows[outsider]["schema"] == "teste"
