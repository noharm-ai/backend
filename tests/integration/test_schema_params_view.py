"""Integration tests for ``GET /schema-params``: the schema params of the
user's schema, read only, for maintainers (the prescription screen shows them
from the alerts card; the admin project edits them).

The noharm-store is stubbed (tests never call AWS): the autouse fixture finds no
item, and each test that needs one patches the read again.
"""

import pytest

from security.role import Role
from tests.conftest import get_access, make_headers

_URL = "/schema-params"


@pytest.fixture
def maintainer_headers(client):
    """Headers with CURATOR role, which holds the MAINTAINER permission"""
    return make_headers(get_access(client, roles=[Role.CURATOR.value]))


def _store(monkeypatch, items: dict):
    monkeypatch.setattr(
        "repository.store_repository.get_item_data",
        lambda pk, sk: items.get(sk) if pk == "schema_params" else None,
    )


def _view(client, headers) -> dict:
    response = client.get(_URL, headers=headers)
    assert response.status_code == 200, response.get_json()
    return response.get_json()["data"]


def test_only_maintainers_can_see_the_schema_params(client, analyst_headers):
    """A pharmacist cannot open the schema params"""
    response = client.get(_URL, headers=analyst_headers)

    assert response.status_code == 401


def test_without_an_item_the_defaults_are_in_force(client, maintainer_headers):
    """No item for the schema: the code defaults, and nothing custom"""
    data = _view(client, maintainer_headers)

    assert data["schema"] == "demo"
    assert data["status"] == "not_found"
    assert data["custom"] == {}
    assert data["invalidSections"] == []
    assert data["params"]["alerts"]["types"]["kidney"] == {
        "enabled": True,
        "level": None,
        "adultExams": ["ckd21", "ckd"],
        "pediatricExams": ["swrtz2", "swrtz1"],
    }
    assert data["params"]["alerts"]["interactions"] == {}


def test_the_schema_item_is_shown_with_what_it_sets(
    client, maintainer_headers, monkeypatch
):
    """params: in force (defaults filled in); custom: only what the item sets"""
    _store(
        monkeypatch,
        {
            "demo": {
                "alerts": {
                    "types": {"elderly": {"level": "medium"}},
                    "interactions": {"iy": {"ignoreLevels": ["low"]}},
                }
            },
            "other": {"alerts": {"types": {"kidney": {"enabled": False}}}},
        },
    )

    data = _view(client, maintainer_headers)

    assert data["status"] == "found"
    assert data["custom"] == {
        "alerts": {
            "types": {"elderly": {"level": "medium"}},
            "interactions": {"iy": {"ignoreLevels": ["low"]}},
        }
    }
    assert data["params"]["alerts"]["types"]["elderly"] == {
        "enabled": True,
        "level": "medium",
    }
    # another schema's item does not apply
    assert data["params"]["alerts"]["types"]["kidney"]["enabled"] is True
    assert data["params"]["alerts"]["interactions"]["iy"]["enabled"] is True


def test_an_invalid_section_is_named(client, maintainer_headers, monkeypatch):
    """An invalid section is left out (defaults) and named for the maintainer"""
    _store(
        monkeypatch,
        {"demo": {"alerts": {"types": {"kidney": {"enabled": "talvez"}}}}},
    )

    data = _view(client, maintainer_headers)

    assert data["status"] == "found"
    assert data["invalidSections"] == ["alerts"]
    assert data["custom"] == {}


def test_a_read_failure_is_reported(client, maintainer_headers, monkeypatch):
    """The table could not be read: the defaults are in force, and it says so"""

    def fail(pk, sk):
        raise RuntimeError("timeout")

    monkeypatch.setattr("repository.store_repository.get_item_data", fail)

    data = _view(client, maintainer_headers)

    assert data["status"] == "read_error"
    assert data["custom"] == {}


def test_the_view_skips_the_container_cache(client, maintainer_headers, monkeypatch):
    """The prescription view caches the params per container; this view always
    reads the table, so it shows what admin saved before the cache expires"""
    from services import schema_params_service

    monkeypatch.setattr(schema_params_service, "CACHE_TTL_SECONDS", 60)
    _store(monkeypatch, {})
    schema_params_service.get_schema_params(schema="demo")

    _store(monkeypatch, {"demo": {"alerts": {"types": {"kidney": {"enabled": False}}}}})
    data = _view(client, maintainer_headers)

    assert data["status"] == "found"
    assert data["custom"]["alerts"]["types"]["kidney"]["enabled"] is False
