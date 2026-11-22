"""Integration tests for ``GET /schema-params``: the schema params of the
user's schema, read only, for maintainers (the prescription screen shows them
from the alerts card; the admin project edits them).

The params are the demo schema's memoria record (`schema-params`), written by
the schema_params fixture as the admin project does; without it the code
defaults apply.
"""

import pytest

from security.role import Role
from tests.conftest import get_access, make_headers

_URL = "/schema-params"


@pytest.fixture
def maintainer_headers(client):
    """Headers with CURATOR role, which holds the MAINTAINER permission"""
    return make_headers(get_access(client, roles=[Role.CURATOR.value]))


def _view(client, headers) -> dict:
    response = client.get(_URL, headers=headers)
    assert response.status_code == 200, response.get_json()
    return response.get_json()["data"]


def test_only_maintainers_can_see_the_schema_params(client, analyst_headers):
    """A pharmacist cannot open the schema params"""
    response = client.get(_URL, headers=analyst_headers)

    assert response.status_code == 401


def test_without_a_record_the_defaults_are_in_force(client, maintainer_headers):
    """No record for the schema: the code defaults, and nothing custom"""
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


def test_the_schema_record_is_shown_with_what_it_sets(
    client, maintainer_headers, schema_params
):
    """params: in force (defaults filled in); custom: only what the record sets"""
    schema_params(
        {
            "alerts": {
                "types": {"elderly": {"level": "medium"}},
                "interactions": {"iy": {"ignoreLevels": ["low"]}},
            }
        }
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
    assert data["params"]["alerts"]["types"]["kidney"]["enabled"] is True
    assert data["params"]["alerts"]["interactions"]["iy"]["enabled"] is True


def test_an_invalid_section_is_named(client, maintainer_headers, schema_params):
    """An invalid section is left out (defaults) and named for the maintainer"""
    schema_params({"alerts": {"types": {"kidney": {"enabled": "talvez"}}}})

    data = _view(client, maintainer_headers)

    assert data["status"] == "found"
    assert data["invalidSections"] == ["alerts"]
    assert data["custom"] == {}


def test_a_change_applies_on_the_next_request(
    client, maintainer_headers, schema_params
):
    """No cache: a record admin saves is in force on the next request"""
    schema_params({"alerts": {"types": {"kidney": {"enabled": False}}}})
    before = _view(client, maintainer_headers)

    schema_params({"alerts": {"types": {"kidney": {"enabled": True}}}})
    after = _view(client, maintainer_headers)

    assert before["params"]["alerts"]["types"]["kidney"]["enabled"] is False
    assert after["params"]["alerts"]["types"]["kidney"]["enabled"] is True
