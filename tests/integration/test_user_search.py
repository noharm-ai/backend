"""Integration tests for GET /users/search (user_service.search_users).

The endpoint feeds the "responsible user" pickers in the frontend, so it only
ever exposes users of the caller's own schema, hides NoHarm support accounts,
and sorts active users first. Test rows live in the shared ``public.usuario``
table and use a reserved e-mail prefix so the fixture can remove them again.
"""

import json

import pytest
from sqlalchemy import text

from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit

_EMAIL_PREFIX = "zztest_usrsearch_"
_TERM = "zztestpicker"
"""Distinctive fragment shared by every seeded name, used as the search term."""


def _add_user(name: str, suffix: str, config, schema="demo", active=True):
    """Insert a public.usuario row carrying the reserved e-mail prefix."""
    session.execute(
        text(
            "INSERT INTO public.usuario (nome, email, senha, schema, config, ativo) "
            "VALUES (:name, :email, 'x', :schema, CAST(:config AS json), :active)"
        ),
        {
            "name": name,
            "email": f"{_EMAIL_PREFIX}{suffix}@example.com",
            "schema": schema,
            "config": json.dumps(config) if config is not None else None,
            "active": active,
        },
    )
    session_commit()


@pytest.fixture
def seed_searchable_users():
    """Users covering every branch of the search filter, removed afterwards."""

    def _delete():
        session.execute(
            text("DELETE FROM public.usuario WHERE email LIKE :prefix"),
            {"prefix": f"{_EMAIL_PREFIX}%"},
        )
        session_commit()

    _delete()

    # names are deliberately out of insertion order so the ordering assertions
    # cannot pass by accident
    _add_user(f"Beltrano {_TERM} B", "b", {"roles": ["PRESCRIPTION_ANALYST"]})
    _add_user(f"Ciclano {_TERM} A", "a", {"roles": ["VIEWER"]})
    _add_user(f"Fulano {_TERM} C", "c", {"roles": ["VIEWER"]}, active=False)
    _add_user(f"Suporte {_TERM} D", "d", {"roles": ["suporte", "VIEWER"]})
    _add_user(f"Outro Esquema {_TERM} E", "e", {"roles": ["VIEWER"]}, schema="hsc_test")
    _add_user(f"Sem Config {_TERM} F", "f", {})

    yield

    _delete()


def _names(response):
    """Names returned by the endpoint, in response order."""
    return [item["name"] for item in response.get_json()["data"]]


def test_search_users_permission_denied(client, seed_searchable_users):
    """Without READ_BASIC_FEATURES the search is rejected [401 UNAUTHORIZED]."""
    headers = make_headers(get_access(client, roles=[Role.DISPENSING_MANAGER.value]))
    response = client.get(
        "/users/search", query_string={"term": _TERM}, headers=headers
    )

    assert response.status_code == 401


def test_search_users_matches_term_case_insensitively(
    client, analyst_headers, seed_searchable_users
):
    """The term matches any part of the name, ignoring case [200 OK]."""
    response = client.get(
        "/users/search", query_string={"term": _TERM.upper()}, headers=analyst_headers
    )

    assert response.status_code == 200
    names = _names(response)
    assert f"Beltrano {_TERM} B" in names
    assert f"Ciclano {_TERM} A" in names


def test_search_users_returns_only_id_and_name(
    client, analyst_headers, seed_searchable_users
):
    """Each hit carries just the id and the name — no e-mail or config leaks."""
    response = client.get(
        "/users/search", query_string={"term": _TERM}, headers=analyst_headers
    )

    assert response.status_code == 200
    items = response.get_json()["data"]
    assert items
    for item in items:
        assert set(item.keys()) == {"id", "name"}
        assert isinstance(item["id"], int)


def test_search_users_hides_support_accounts(
    client, analyst_headers, seed_searchable_users
):
    """Users holding the 'suporte' role are never offered to the schema."""
    response = client.get(
        "/users/search", query_string={"term": _TERM}, headers=analyst_headers
    )

    assert response.status_code == 200
    assert f"Suporte {_TERM} D" not in _names(response)


def test_search_users_keeps_users_without_roles(
    client, analyst_headers, seed_searchable_users
):
    """A user whose config carries no roles is still searchable.

    The support filter is expressed as "roles do not contain suporte OR roles
    is null", so a config without the key must not drop the user.
    """
    response = client.get(
        "/users/search", query_string={"term": _TERM}, headers=analyst_headers
    )

    assert response.status_code == 200
    assert f"Sem Config {_TERM} F" in _names(response)


def test_search_users_restricted_to_caller_schema(
    client, analyst_headers, seed_searchable_users
):
    """A matching user of another schema is not returned."""
    response = client.get(
        "/users/search", query_string={"term": _TERM}, headers=analyst_headers
    )

    assert response.status_code == 200
    assert f"Outro Esquema {_TERM} E" not in _names(response)


def test_search_users_orders_active_first_then_by_name(
    client, analyst_headers, seed_searchable_users
):
    """Active users come first, and within each group names are ascending."""
    response = client.get(
        "/users/search", query_string={"term": _TERM}, headers=analyst_headers
    )

    assert response.status_code == 200
    assert _names(response) == [
        f"Beltrano {_TERM} B",
        f"Ciclano {_TERM} A",
        f"Sem Config {_TERM} F",
        # inactive, so last despite sorting before the others alphabetically
        f"Fulano {_TERM} C",
    ]


def test_search_users_unknown_term_returns_empty_list(
    client, analyst_headers, seed_searchable_users
):
    """A term nobody matches yields an empty list rather than an error."""
    response = client.get(
        "/users/search",
        query_string={"term": "zzt-no-such-user"},
        headers=analyst_headers,
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == []
