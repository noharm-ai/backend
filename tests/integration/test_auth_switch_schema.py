"""Integration tests for ``/switch-schema`` — who may change tenant, and into what.

A NoHarm session is bound to one PostgreSQL schema, so switching tenant means
minting a new token for another one. Two things decide what a user gets:

* ``GET /switch-schema`` answers the picker: a maintainer may go anywhere and
  gets every configured schema; a plain ``MULTI_SCHEMA`` user gets only the
  schemas recorded on their ``usuario_extra`` row, and ``maintainer: false``
  along with them, because the flag is what the frontend uses to decide whether
  to offer the whole list;
* ``POST /switch-schema`` re-authenticates into the chosen one, and has to refuse
  a schema the caller was never listed for — the switch target ends up in a
  ``schema_translate_map``, so an unchecked string is a cross-tenant read.

``TRAINING`` (which may record in any schema) and ``runAsRole`` are covered by
``test_role_training``; what these tests add is the maintainer path, the
``usuario_extra`` path and the ``NAVIGATOR`` session, which is downgraded to
read-only roles whenever it lands in a schema that is not the user's own.

The seeded users are used as they ship: ``organizationmanager`` carries
``ORGANIZATION_MANAGER`` plus two schemas on ``usuario_extra``, and the demo user
carries none.
"""

import pytest

from models.appendix import SchemaConfig
from models.main import User
from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit
from utils import status

SWITCH_URL = "/switch-schema"

# the seeded tenant the demo user does not belong to
OTHER_SCHEMA = "teste"
# a name no schema_config row carries
UNKNOWN_SCHEMA = "teste2"

_ORG_MANAGER_EMAIL = "organizationmanager"


def _configured_schemas():
    """Every schema the installation knows about, as the picker sorts them."""
    return sorted(s.schemaName for s in session.query(SchemaConfig).all())


@pytest.fixture
def org_manager_headers(client):
    """Headers of the seeded ORGANIZATION_MANAGER.

    The role and the two allowed schemas live on ``usuario_extra``; the user's own
    config only carries ``VIEWER``, which is what the seed ships and what the
    fixture restores on the way out.
    """
    saved = session.query(User).filter(User.email == _ORG_MANAGER_EMAIL).first().config

    yield make_headers(
        get_access(
            client,
            email=_ORG_MANAGER_EMAIL,
            password=_ORG_MANAGER_EMAIL,
            roles=[Role.VIEWER.value],
        )
    )

    user = session.query(User).filter(User.email == _ORG_MANAGER_EMAIL).first()
    user.config = saved
    session_commit()


@pytest.fixture
def org_navigator_headers(client):
    """Headers of the ORGANIZATION_MANAGER acting as a NAVIGATOR.

    The ``usuario_extra`` row already allows the two schemas, so this is the one
    seeded user that can reach a foreign schema as a NAVIGATOR without
    MAINTAINER.
    """
    saved = session.query(User).filter(User.email == _ORG_MANAGER_EMAIL).first().config

    yield make_headers(
        get_access(
            client,
            email=_ORG_MANAGER_EMAIL,
            password=_ORG_MANAGER_EMAIL,
            roles=[Role.NAVIGATOR.value],
        )
    )

    user = session.query(User).filter(User.email == _ORG_MANAGER_EMAIL).first()
    user.config = saved
    session_commit()


# --- GET: the schemas offered to the picker ---


def test_maintainer_is_offered_every_configured_schema(client, admin_headers):
    """A maintainer may go anywhere, so the picker lists the whole installation."""
    response = client.get(SWITCH_URL, headers=admin_headers)

    assert response.status_code == status.HTTP_200_OK

    data = response.get_json()["data"]
    assert data["maintainer"] is True
    assert [s["name"] for s in data["schemas"]] == _configured_schemas()


def test_maintainer_schemas_carry_the_name_only(client, admin_headers):
    """The maintainer listing is built from schema_config, not from user config."""
    response = client.get(SWITCH_URL, headers=admin_headers)

    assert response.status_code == status.HTTP_200_OK

    for schema in response.get_json()["data"]["schemas"]:
        assert set(schema.keys()) == {"name"}


def test_a_multi_schema_user_is_offered_their_own_schemas(client, org_manager_headers):
    """Without MAINTAINER the picker shows the usuario_extra list, verbatim."""
    response = client.get(SWITCH_URL, headers=org_manager_headers)

    assert response.status_code == status.HTTP_200_OK

    data = response.get_json()["data"]
    assert data["maintainer"] is False
    assert [s["name"] for s in data["schemas"]] == ["demo", OTHER_SCHEMA]
    # the friendly name is what the picker shows, so it has to survive the trip
    assert all(s.get("friendlyName") for s in data["schemas"])


def test_a_multi_schema_user_without_extra_config_is_offered_nothing(
    client, navigator_headers
):
    """MULTI_SCHEMA alone grants no schema: the demo user has no usuario_extra row."""
    response = client.get(SWITCH_URL, headers=navigator_headers)

    assert response.status_code == status.HTTP_200_OK

    data = response.get_json()["data"]
    assert data["maintainer"] is False
    assert data["schemas"] == []


def test_reading_the_picker_requires_multi_schema(client, analyst_headers):
    """A role without MULTI_SCHEMA may not even enumerate the schemas [401]."""
    response = client.get(SWITCH_URL, headers=analyst_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# --- POST: the switch itself ---


def test_a_listed_schema_is_switched_into(client, org_manager_headers):
    """A schema on the usuario_extra list mints a session for that tenant."""
    response = client.post(
        SWITCH_URL, json={"schema": OTHER_SCHEMA}, headers=org_manager_headers
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["schema"] == OTHER_SCHEMA


def test_an_unlisted_schema_is_refused(client, org_manager_headers):
    """A schema the user was never listed for is rejected, configured or not [401]."""
    response = client.post(
        SWITCH_URL, json={"schema": UNKNOWN_SCHEMA}, headers=org_manager_headers
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_a_user_with_no_schemas_cannot_switch(client, navigator_headers):
    """MULTI_SCHEMA with an empty list switches nowhere, not everywhere [401]."""
    response = client.post(
        SWITCH_URL, json={"schema": OTHER_SCHEMA}, headers=navigator_headers
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_switching_requires_multi_schema(client, analyst_headers):
    """A role without MULTI_SCHEMA cannot switch at all [401]."""
    response = client.post(
        SWITCH_URL, json={"schema": OTHER_SCHEMA}, headers=analyst_headers
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_a_maintainer_switches_into_any_configured_schema(client, admin_headers):
    """MAINTAINER skips the list check — every configured schema is reachable."""
    response = client.post(
        SWITCH_URL, json={"schema": OTHER_SCHEMA}, headers=admin_headers
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["schema"] == OTHER_SCHEMA


# --- POST: the NAVIGATOR downgrade in a foreign schema ---


def test_a_navigator_is_downgraded_in_a_foreign_schema(client, org_navigator_headers):
    """A NAVIGATOR visiting another tenant keeps navigation and read access only."""
    response = client.post(
        SWITCH_URL, json={"schema": OTHER_SCHEMA}, headers=org_navigator_headers
    )

    assert response.status_code == status.HTTP_200_OK

    data = response.get_json()["data"]
    assert data["schema"] == OTHER_SCHEMA
    assert data["roles"] == [Role.NAVIGATOR.value, Role.VIEWER.value]


def test_a_navigator_keeps_its_roles_in_its_own_schema(client, org_navigator_headers):
    """The downgrade is about being a visitor, so the home schema is untouched."""
    response = client.post(
        SWITCH_URL, json={"schema": "demo"}, headers=org_navigator_headers
    )

    assert response.status_code == status.HTTP_200_OK

    data = response.get_json()["data"]
    assert data["schema"] == "demo"
    assert Role.ORGANIZATION_MANAGER.value in data["roles"]
