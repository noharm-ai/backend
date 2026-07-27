"""Integration tests for the /lists/icds endpoint (lists_service.list_icds)."""

import pytest
from sqlalchemy import text

from tests.conftest import get_access, make_headers, session, session_commit

from security.role import Role

# ICD test rows live in the shared public.tb_cid10 table. Use a high co_cid10
# range and distinctive names so the rows never collide with real seed data
# and are trivial to clean up afterwards. nu_cid10 is capped at 4 chars.
_ICD_ACTIVE_A = (999001, "ZZ1", "ZZTest Cholera", 1)
_ICD_ACTIVE_B = (999002, "ZZ2", "ZZTest Anthrax", 1)
_ICD_INACTIVE = (999003, "ZZ3", "ZZTest Retired", 0)

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


def test_list_icds_permission_denied(client):
    """A user without READ_BASIC_FEATURES cannot list ICDs [401 UNAUTHORIZED]."""
    headers = make_headers(get_access(client, roles=[Role.SUPPORT_REQUESTER.value]))
    response = client.get("/lists/icds", headers=headers)

    assert response.status_code == 401


def test_list_icds_returns_formatted_active_rows(client, analyst_headers, seed_icds):
    """Active ICDs are returned as '{id_str} - {name}' with the code as id."""
    response = client.get("/lists/icds", headers=analyst_headers)

    assert response.status_code == 200
    items = _data(response)
    by_id = {item["id"]: item["name"] for item in items}

    assert _ICD_ACTIVE_A[1] in by_id
    assert by_id[_ICD_ACTIVE_A[1]] == f"{_ICD_ACTIVE_A[1]} - {_ICD_ACTIVE_A[2]}"
    assert by_id[_ICD_ACTIVE_B[1]] == f"{_ICD_ACTIVE_B[1]} - {_ICD_ACTIVE_B[2]}"


def test_list_icds_excludes_inactive_rows(client, analyst_headers, seed_icds):
    """ICDs with st_ativo != 1 are omitted from the listing."""
    response = client.get("/lists/icds", headers=analyst_headers)

    assert response.status_code == 200
    ids = {item["id"] for item in _data(response)}
    assert _ICD_INACTIVE[1] not in ids


def test_list_icds_ordered_by_name(client, analyst_headers, seed_icds):
    """Results are ordered alphabetically by ICD name (no_cid10)."""
    response = client.get("/lists/icds", headers=analyst_headers)

    assert response.status_code == 200
    items = _data(response)
    positions = {
        item["id"]: index
        for index, item in enumerate(items)
        if item["id"] in (_ICD_ACTIVE_A[1], _ICD_ACTIVE_B[1])
    }

    # "ZZTest Anthrax" (B) must precede "ZZTest Cholera" (A).
    assert positions[_ICD_ACTIVE_B[1]] < positions[_ICD_ACTIVE_A[1]]
