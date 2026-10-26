"""Integration tests for the /admin/substance endpoint (admin_substance_service).

Covers the single-substance lookup. Rows live in the shared public.substancia /
public.classe tables; the 95000+ sctid range is reserved for this module.
"""

import pytest
from sqlalchemy import text

from tests.conftest import session, session_commit
from tests.utils.utils_test_admin_substance import (
    create_test_substance,
    create_test_substance_class,
)
from utils import status

GET_URL = "/admin/substance"

# sctid range reserved for this module (>= 90000 so the session-wide cleanup in
# tests/conftest.py also catches leftovers, but clear of the unit-conversion ids)
_ALPHA = 95001

_CLASS_A = "ZZTA"


@pytest.fixture(scope="module", autouse=True)
def seed_substances():
    """Create the class and substance this module looks up."""
    create_test_substance_class(_CLASS_A, "ZZTest Class A")

    # Alpha: classified, active, curated, max dose (adult) + default unit, tagged
    create_test_substance(
        id=_ALPHA,
        name="ZZTest Subs Alpha",
        id_class=_CLASS_A,
        active=True,
        admin_text="curated text",
        default_measureunit="mg",
        maxdose_adult=100,
        tags=["zzt-shared", "zzt-alpha"],
        updated_by=1,
    )

    yield

    session.execute(
        text("DELETE FROM public.substancia WHERE sctid IN :ids").bindparams(
            ids=(_ALPHA,)
        )
    )
    session.execute(
        text("DELETE FROM public.classe WHERE idclasse IN :ids").bindparams(
            ids=(_CLASS_A,)
        )
    )
    session_commit()


def test_get_substance_returns_the_full_dto(client, admin_headers):
    """Get: a known substance returns its attributes plus class and responsible"""
    response = client.get(f"{GET_URL}/{_ALPHA}", headers=admin_headers)

    assert response.status_code == status.HTTP_200_OK
    data = response.get_json()["data"]
    assert data["id"] == str(_ALPHA)
    assert data["name"] == "ZZTest Subs Alpha"
    assert data["idClass"] == _CLASS_A
    assert data["className"] == "ZZTest Class A"
    assert data["responsible"] == "Demonstração"
    assert data["active"] is True
    assert data["adminText"] == "curated text"
    assert data["maxdoseAdult"] == 100
    assert data["defaultMeasureUnit"] == "mg"
    assert data["tags"] == ["zzt-shared", "zzt-alpha"]


def test_get_unknown_substance_returns_not_found(client, admin_headers):
    """Get: an unknown substance id returns 404"""
    response = client.get(f"{GET_URL}/99999999", headers=admin_headers)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.get_json()["code"] == "errors.notFound"


def test_get_requires_the_admin_substances_permission(client, analyst_headers):
    """Get: a role without ADMIN_SUBSTANCES is rejected"""
    response = client.get(f"{GET_URL}/{_ALPHA}", headers=analyst_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_curator_can_get_substances(client, curator_headers):
    """Get: the curator role also holds ADMIN_SUBSTANCES"""
    response = client.get(f"{GET_URL}/{_ALPHA}", headers=curator_headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["id"] == str(_ALPHA)
