"""Integration tests for ``GET /admin/drug/ref``
(``admin_drug_service.get_drug_ref``) — the curation notes stored on a
substance, shown next to the drug being curated.

Fixtures use the reserved ``>= 90000`` id range (91400 block) so the
session-scoped ``clean_test_artifacts`` fixture removes them.
"""

import pytest
from sqlalchemy import text

from tests.conftest import session, session_commit

REF_URL = "/admin/drug/ref"

# ids reserved for this module
_SUBSTANCE_WITH_REF = 9140001
_SUBSTANCE_WITHOUT_REF = 9140002
_UNKNOWN_SUBSTANCE = 9140099

_NAME_WITH_REF = "ZZTEST ADMIN SUBSTANCIA CURADA"
_NAME_WITHOUT_REF = "ZZTEST ADMIN SUBSTANCIA SEM CURADORIA"
_REF_TEXT = "Ajustar dose na insuficiência renal."


@pytest.fixture
def curation_substances():
    """Two substances: one with curation notes, one without."""
    for sctid, name, ref in (
        (_SUBSTANCE_WITH_REF, _NAME_WITH_REF, _REF_TEXT),
        (_SUBSTANCE_WITHOUT_REF, _NAME_WITHOUT_REF, None),
    ):
        session.execute(
            text(
                "INSERT INTO public.substancia (sctid, nome, link, ativo, curadoria) "
                "VALUES (:sctid, :name, '', true, :ref)"
            ),
            {"sctid": sctid, "name": name, "ref": ref},
        )
    session_commit()

    yield

    session.execute(text("DELETE FROM public.substancia WHERE sctid >= 9140000"))
    session_commit()


def _data(response):
    """Payload of a successful response."""
    return response.get_json()["data"]


# --- GET /admin/drug/ref -------------------------------------------------------


def test_ref_no_token(client):
    """GET /admin/drug/ref — 401 without authentication."""
    response = client.get(f"{REF_URL}?sctid={_SUBSTANCE_WITH_REF}")

    assert response.status_code == 401


def test_ref_permission_denied(client, analyst_headers):
    """GET /admin/drug/ref — 401 for a role without ADMIN_DRUGS."""
    response = client.get(
        f"{REF_URL}?sctid={_SUBSTANCE_WITH_REF}", headers=analyst_headers
    )

    assert response.status_code == 401


def test_ref_returns_curation_text(client, admin_headers, curation_substances):
    """The substance name and its curation notes come back together."""
    response = client.get(
        f"{REF_URL}?sctid={_SUBSTANCE_WITH_REF}", headers=admin_headers
    )

    assert response.status_code == 200
    assert _data(response) == {"name": _NAME_WITH_REF, "ref": _REF_TEXT}


def test_ref_without_curation_text(client, admin_headers, curation_substances):
    """A substance nobody curated yet resolves with an empty ref."""
    response = client.get(
        f"{REF_URL}?sctid={_SUBSTANCE_WITHOUT_REF}", headers=admin_headers
    )

    assert response.status_code == 200
    assert _data(response) == {"name": _NAME_WITHOUT_REF, "ref": None}


def test_ref_unknown_substance(client, admin_headers):
    """An sctid with no substance behind it is rejected [400]."""
    response = client.get(f"{REF_URL}?sctid={_UNKNOWN_SUBSTANCE}", headers=admin_headers)

    assert response.status_code == 400


def test_ref_without_sctid(client, admin_headers):
    """Omitting sctid is rejected the same way as an unknown one [400]."""
    response = client.get(REF_URL, headers=admin_headers)

    assert response.status_code == 400
