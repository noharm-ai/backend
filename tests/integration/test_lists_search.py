"""Integration tests for the ICD search endpoints.

Covers lists_service.find_icds (GET /lists/icds/find) and
lists_service.find_icds_by_ids (GET /lists/icds/resolve) — both previously
untested. Rows are inserted into the shared public.tb_cid10 table using a high
co_cid10 range with distinctive names so they never collide with real seed
data and are trivial to clean up.
"""

import pytest
from sqlalchemy import text

from tests.conftest import get_access, make_headers, session, session_commit

from security.role import Role

# (co_cid10, nu_cid10 code, no_cid10 name, st_ativo). nu_cid10 is capped at 4 chars.
_ICD_ACTIVE_A = (999101, "YZ1", "YZTest Malaria", 1)
_ICD_ACTIVE_B = (999102, "YZ2", "YZTest Dengue", 1)
_ICD_INACTIVE = (999103, "YZ3", "YZTest Retired", 0)

_ALL_IDS = (_ICD_ACTIVE_A[0], _ICD_ACTIVE_B[0], _ICD_INACTIVE[0])


@pytest.fixture
def seed_icds():
    """Insert distinctive tb_cid10 rows and remove them after the test."""
    for co, nu, no, active in (_ICD_ACTIVE_A, _ICD_ACTIVE_B, _ICD_INACTIVE):
        session.execute(
            text(
                "INSERT INTO public.tb_cid10 "
                "(co_cid10, nu_cid10, tp_agravo, no_cid10, no_cid10_filtro, st_ativo) "
                "VALUES (:co, :nu, 0, :no, :no, :active)"
            ),
            {"co": co, "nu": nu, "no": no, "active": active},
        )
    session_commit()

    yield

    session.execute(
        text("DELETE FROM public.tb_cid10 WHERE co_cid10 IN (:a, :b, :c)"),
        {"a": _ALL_IDS[0], "b": _ALL_IDS[1], "c": _ALL_IDS[2]},
    )
    session_commit()


def _data(response):
    """Extract the data list from a successful response envelope."""
    return response.get_json()["data"]


# --- find (search by term) -------------------------------------------------


def test_find_icds_permission_denied(client):
    """A user without READ_BASIC_FEATURES cannot search ICDs [401]."""
    headers = make_headers(get_access(client, roles=[Role.SUPPORT_REQUESTER.value]))
    response = client.get("/lists/icds/find?term=YZTest", headers=headers)

    assert response.status_code == 401


def test_find_icds_by_description(client, analyst_headers, seed_icds):
    """A term matching the ICD name returns the active row as {id, name}."""
    response = client.get("/lists/icds/find?term=YZTest Malaria", headers=analyst_headers)

    assert response.status_code == 200
    by_id = {item["id"]: item["name"] for item in _data(response)}
    assert by_id.get(_ICD_ACTIVE_A[1]) == _ICD_ACTIVE_A[2]


def test_find_icds_by_code(client, analyst_headers, seed_icds):
    """A term matching the ICD code (nu_cid10) resolves the row."""
    response = client.get(f"/lists/icds/find?term={_ICD_ACTIVE_B[1]}", headers=analyst_headers)

    assert response.status_code == 200
    ids = {item["id"] for item in _data(response)}
    assert _ICD_ACTIVE_B[1] in ids


def test_find_icds_is_case_insensitive(client, analyst_headers, seed_icds):
    """Search matches regardless of term casing (ilike)."""
    response = client.get("/lists/icds/find?term=yztest dengue", headers=analyst_headers)

    assert response.status_code == 200
    ids = {item["id"] for item in _data(response)}
    assert _ICD_ACTIVE_B[1] in ids


def test_find_icds_excludes_inactive_rows(client, analyst_headers, seed_icds):
    """Inactive ICDs (st_ativo != 1) are never returned by search."""
    response = client.get("/lists/icds/find?term=YZTest", headers=analyst_headers)

    assert response.status_code == 200
    ids = {item["id"] for item in _data(response)}
    assert _ICD_INACTIVE[1] not in ids
    assert _ICD_ACTIVE_A[1] in ids
    assert _ICD_ACTIVE_B[1] in ids


def test_find_icds_empty_term_is_rejected(client, analyst_headers):
    """An empty search term is a business-rule error [400]."""
    response = client.get("/lists/icds/find?term=", headers=analyst_headers)

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"


# --- resolve (lookup by codes) --------------------------------------------


def test_resolve_icds_permission_denied(client):
    """A user without READ_BASIC_FEATURES cannot resolve ICDs [401]."""
    headers = make_headers(get_access(client, roles=[Role.SUPPORT_REQUESTER.value]))
    response = client.get(f"/lists/icds/resolve?ids={_ICD_ACTIVE_A[1]}", headers=headers)

    assert response.status_code == 401


def test_resolve_icds_returns_matching_codes(client, analyst_headers, seed_icds):
    """Codes passed in ids resolve to their {id, name} records."""
    ids = f"{_ICD_ACTIVE_A[1]},{_ICD_ACTIVE_B[1]}"
    response = client.get(f"/lists/icds/resolve?ids={ids}", headers=analyst_headers)

    assert response.status_code == 200
    by_id = {item["id"]: item["name"] for item in _data(response)}
    assert by_id.get(_ICD_ACTIVE_A[1]) == _ICD_ACTIVE_A[2]
    assert by_id.get(_ICD_ACTIVE_B[1]) == _ICD_ACTIVE_B[2]


def test_resolve_icds_includes_inactive(client, analyst_headers, seed_icds):
    """Resolve looks up by code without filtering on status, unlike find."""
    response = client.get(f"/lists/icds/resolve?ids={_ICD_INACTIVE[1]}", headers=analyst_headers)

    assert response.status_code == 200
    ids = {item["id"] for item in _data(response)}
    assert _ICD_INACTIVE[1] in ids


def test_resolve_icds_empty_returns_empty_list(client, analyst_headers):
    """No ids yields an empty list rather than an error."""
    response = client.get("/lists/icds/resolve?ids=", headers=analyst_headers)

    assert response.status_code == 200
    assert _data(response) == []
