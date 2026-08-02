"""Integration tests for the /protocol/list endpoint (protocol_service.list_protocols)."""

import pytest
from sqlalchemy import text

from tests.conftest import get_access, make_headers, session, session_commit

from security.role import Role

# Protocol test rows live in the shared public.protocolo table. Use a high
# idprotocolo range so they never collide with real seed data and are trivial
# to clean up afterwards. tp_protocolo/tp_situacao follow ProtocolTypeEnum and
# ProtocolStatusTypeEnum: type 1 = PRESCRIPTION_AGG, 2 = PRESCRIPTION_INDIVIDUAL;
# status 0 = INACTIVE, 1 = ACTIVE.
#
# Fields: (id, schema_name, name, tp_protocolo, tp_situacao)
_GLOBAL_ACTIVE = (990001, None, "ZZTest Global Agg", 1, 1)
_DEMO_ACTIVE = (990002, "demo", "ZZTest Demo Individual", 2, 1)
_DEMO_INACTIVE = (990003, "demo", "ZZTest Demo Inactive", 1, 0)
_OTHER_SCHEMA = (990004, "other-schema", "ZZTest Other Schema", 1, 1)

_ALL_ROWS = (_GLOBAL_ACTIVE, _DEMO_ACTIVE, _DEMO_INACTIVE, _OTHER_SCHEMA)
_ALL_IDS = tuple(row[0] for row in _ALL_ROWS)


@pytest.fixture
def seed_protocols():
    """Insert distinctive protocolo rows and remove them after the test."""
    for id_protocol, schema, name, tp_protocolo, tp_situacao in _ALL_ROWS:
        session.execute(
            text(
                "INSERT INTO public.protocolo "
                "(idprotocolo, schema_name, nome, tp_protocolo, tp_situacao, "
                "configuracao, created_at, created_by) "
                "VALUES (:id, :schema, :name, :tp_protocolo, :tp_situacao, "
                "CAST('{}' AS json), now(), 1)"
            ),
            {
                "id": id_protocol,
                "schema": schema,
                "name": name,
                "tp_protocolo": tp_protocolo,
                "tp_situacao": tp_situacao,
            },
        )
    session_commit()

    yield

    session.execute(
        text("DELETE FROM public.protocolo WHERE idprotocolo IN :ids").bindparams(
            ids=_ALL_IDS
        )
    )
    session_commit()


def _data(response):
    """Extract the data list from a successful response envelope."""
    return response.get_json()["data"]


def _by_id(response):
    """Index the returned protocols by their id for easy assertions."""
    return {item["id"]: item for item in _data(response)}


def test_list_protocols_permission_denied(client):
    """A user without READ_BASIC_FEATURES cannot list protocols [401 UNAUTHORIZED]."""
    headers = make_headers(get_access(client, roles=[Role.SUPPORT_REQUESTER.value]))
    response = client.get("/protocol/list", headers=headers)

    assert response.status_code == 401


def test_list_protocols_returns_visible_rows(client, analyst_headers, seed_protocols):
    """Global (schema-less) and same-schema protocols are returned together."""
    response = client.get("/protocol/list", headers=analyst_headers)

    assert response.status_code == 200
    by_id = _by_id(response)

    # Global and demo-owned protocols are visible...
    assert _GLOBAL_ACTIVE[0] in by_id
    assert _DEMO_ACTIVE[0] in by_id
    assert _DEMO_INACTIVE[0] in by_id
    # ...but a protocol owned by another schema is hidden.
    assert _OTHER_SCHEMA[0] not in by_id


def test_list_protocols_response_shape(client, analyst_headers, seed_protocols):
    """Each protocol exposes id, name, protocolType and status fields."""
    response = client.get("/protocol/list", headers=analyst_headers)

    assert response.status_code == 200
    item = _by_id(response)[_DEMO_ACTIVE[0]]

    assert item["name"] == _DEMO_ACTIVE[2]
    assert item["protocolType"] == _DEMO_ACTIVE[3]
    assert item["status"] == _DEMO_ACTIVE[4]


def test_list_protocols_filter_by_type(client, analyst_headers, seed_protocols):
    """Filtering by protocolType returns only protocols of that type."""
    response = client.get("/protocol/list?protocolType=2", headers=analyst_headers)

    assert response.status_code == 200
    by_id = _by_id(response)

    # Only the type-2 (individual) protocol among the seeded rows is returned.
    assert _DEMO_ACTIVE[0] in by_id
    assert _GLOBAL_ACTIVE[0] not in by_id
    assert _DEMO_INACTIVE[0] not in by_id


def test_list_protocols_filter_by_status(client, analyst_headers, seed_protocols):
    """Filtering by statusType returns only protocols in that status."""
    response = client.get("/protocol/list?statusType=0", headers=analyst_headers)

    assert response.status_code == 200
    by_id = _by_id(response)

    # Only the inactive (status 0) seeded protocol is returned.
    assert _DEMO_INACTIVE[0] in by_id
    assert _GLOBAL_ACTIVE[0] not in by_id
    assert _DEMO_ACTIVE[0] not in by_id


def test_list_protocols_active_flag_keeps_only_active(
    client, analyst_headers, seed_protocols
):
    """The active flag restricts the listing to ACTIVE protocols."""
    response = client.get("/protocol/list?active=true", headers=analyst_headers)

    assert response.status_code == 200
    by_id = _by_id(response)

    # Active protocols remain, the inactive one is dropped.
    assert _GLOBAL_ACTIVE[0] in by_id
    assert _DEMO_ACTIVE[0] in by_id
    assert _DEMO_INACTIVE[0] not in by_id


def test_list_protocols_ordered_by_name(client, analyst_headers, seed_protocols):
    """Results are ordered alphabetically by protocol name."""
    response = client.get("/protocol/list", headers=analyst_headers)

    assert response.status_code == 200
    items = _data(response)
    positions = {
        item["id"]: index
        for index, item in enumerate(items)
        if item["id"] in (_GLOBAL_ACTIVE[0], _DEMO_ACTIVE[0], _DEMO_INACTIVE[0])
    }

    # "ZZTest Demo Inactive" < "ZZTest Demo Individual" < "ZZTest Global Agg".
    assert positions[_DEMO_INACTIVE[0]] < positions[_DEMO_ACTIVE[0]]
    assert positions[_DEMO_ACTIVE[0]] < positions[_GLOBAL_ACTIVE[0]]
