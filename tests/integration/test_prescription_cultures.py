"""Integration tests for GET /prescriptions/<idPrescription>/cultures

The culture card loads its data here, on demand, instead of through the
prescription view. DynamoDB is skipped in the TEST env
(repository/culture_repository), so the summary is always empty: what these
tests reach is the route, its permission and the contract with the view.

The CULTURE feature gate that precedes the lookup is covered by
tests/unit/test_prescription_cultures_feature.py -- with DynamoDB skipped the
route answers the same empty list either way, so only the unit test can see it.
"""

from mobile import app as flask_app
from models.enums import AntimicrobialLevelEnum
from models.main import Substance
from repository import substance_repository
from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit

# Seed prescription already in the test database (from noharm-ai/database fixtures)
SEED_PRESCRIPTION_ID = "199"
# Seed substances already in the test database
SEED_SUBSTANCE_ID = 10001
SEED_SUBSTANCE_ID_UNCLASSIFIED = 10002


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


def test_antimicrobial_levels_read_the_curated_column(client):  # noqa: ARG001
    """The AWaRe classification the card states comes from substancia.tp_nivel_atb.

    The column is curated outside the app, so what this asserts is the mapping
    and the query: a substance that was never classified answers None, and one
    that is not in the antibiogram is not in the answer at all.
    """
    with flask_app.app_context():
        session.query(Substance).filter(Substance.id == SEED_SUBSTANCE_ID).update(
            {"atb_level": AntimicrobialLevelEnum.RESERVE.value}
        )
        session_commit()

        try:
            levels = substance_repository.get_antimicrobial_levels(
                sctids=[SEED_SUBSTANCE_ID, SEED_SUBSTANCE_ID_UNCLASSIFIED, 999999]
            )
        finally:
            # the seed is shared with every other test of the suite
            session.query(Substance).filter(Substance.id == SEED_SUBSTANCE_ID).update(
                {"atb_level": None}
            )
            session_commit()

    assert levels[SEED_SUBSTANCE_ID] == AntimicrobialLevelEnum.RESERVE.value
    assert levels[SEED_SUBSTANCE_ID_UNCLASSIFIED] is None
    assert 999999 not in levels


def test_antimicrobial_levels_without_substances():
    with flask_app.app_context():
        assert substance_repository.get_antimicrobial_levels(sctids=[]) == {}
        assert substance_repository.get_antimicrobial_levels(sctids=None) == {}
