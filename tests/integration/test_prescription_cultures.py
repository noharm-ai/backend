"""Integration tests for GET /prescriptions/<idPrescription>/cultures

The culture card loads its data here, on demand, instead of through the
prescription view. DynamoDB is skipped in the TEST env
(repository/culture_repository), so the summary is always empty: what these
tests reach is the route, its permission and the contract with the view.

The CULTURE feature gate that precedes the lookup is covered by
tests/unit/test_prescription_cultures_feature.py -- with DynamoDB skipped the
route answers the same empty list either way, so only the unit test can see it.
"""

from security.role import Role
from tests.conftest import get_access, make_headers

# Seed prescription already in the test database (from noharm-ai/database fixtures)
SEED_PRESCRIPTION_ID = "199"


def test_get_cultures_returns_the_card_list(client, analyst_headers):
    response = client.get(
        f"/prescriptions/{SEED_PRESCRIPTION_ID}/cultures", headers=analyst_headers
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"
    assert body["data"] == []


def test_get_cultures_requires_read_prescription(client):
    """The same permission as the prescription view. VIEWER can read
    prescriptions, so the denial is asserted with a role that cannot."""
    headers = make_headers(get_access(client, roles=[Role.STATIC_USER.value]))

    response = client.get(
        f"/prescriptions/{SEED_PRESCRIPTION_ID}/cultures", headers=headers
    )

    assert response.status_code == 401


def test_get_cultures_unknown_prescription(client, analyst_headers):
    response = client.get("/prescriptions/404/cultures", headers=analyst_headers)

    assert response.status_code == 400


def test_prescription_view_carries_only_the_culture_summary(client, analyst_headers):
    """The view no longer embeds the cultures: the card fetches them when it is
    opened, and the tab badge reads the summary."""
    response = client.get(
        f"/prescriptions/{SEED_PRESCRIPTION_ID}", headers=analyst_headers
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert "cultures" not in data
    assert data["cultureStats"] == {"resistantInUse": 0}


# --- alternatives -----------------------------------------------------------

ALTERNATIVES_URL = f"/prescriptions/{SEED_PRESCRIPTION_ID}/cultures/alternatives"


def test_get_alternatives_returns_the_empty_comparison(client, analyst_headers):
    """With DynamoDB skipped there is no antibiogram to compare: the route still
    answers the shape the modal reads, with the substance it was asked about."""
    response = client.get(f"{ALTERNATIVES_URL}?sctid=1111", headers=analyst_headers)

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"
    assert body["data"]["sctid"] == 1111
    assert body["data"]["drug"] is None
    assert body["data"]["cultures"] == []
    assert set(body["data"]["substance"]) == {"name", "atbLevel"}


def test_get_alternatives_requires_a_substance(client, analyst_headers):
    response = client.get(ALTERNATIVES_URL, headers=analyst_headers)

    assert response.status_code == 400


def test_get_alternatives_rejects_a_non_numeric_substance(client, analyst_headers):
    """request.args type=int turns an unparsable value into None"""
    response = client.get(f"{ALTERNATIVES_URL}?sctid=abc", headers=analyst_headers)

    assert response.status_code == 400


def test_get_alternatives_requires_read_prescription(client):
    headers = make_headers(get_access(client, roles=[Role.STATIC_USER.value]))

    response = client.get(f"{ALTERNATIVES_URL}?sctid=1111", headers=headers)

    assert response.status_code == 401


def test_get_alternatives_unknown_prescription(client, analyst_headers):
    response = client.get(
        "/prescriptions/404/cultures/alternatives?sctid=1111", headers=analyst_headers
    )

    assert response.status_code == 400
