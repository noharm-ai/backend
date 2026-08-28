"""Integration tests for the /admin/protocol/list, /admin/protocol/<id> and
/admin/protocol/upsert endpoints (admin_protocol_service), focused on the
schema ownership rules."""

import json

import pytest
from sqlalchemy import bindparam, text

from tests.conftest import session, session_commit
from utils import status

LIST_URL = "/admin/protocol/list"
GET_URL = "/admin/protocol"
UPSERT_URL = "/admin/protocol/upsert"
DEPARTMENT_LIST_URL = "/admin/protocol/department/list"

# Rows live in the shared public.protocolo table. The 9901xx range is reserved
# for this module so it never collides with test_protocol.py (9900xx) or real
# seed data.
#
# Fields: (id, schema_name, name)
_GLOBAL = (990101, None, "ZZAdmin Global")
_OWN = (990102, "demo", "ZZAdmin Demo Owned")
_OTHER = (990103, "other-schema", "ZZAdmin Other Schema")

_ALL_ROWS = (_GLOBAL, _OWN, _OTHER)
_ALL_IDS = tuple(row[0] for row in _ALL_ROWS)

# Department fixtures live in demo.setor / demo.segmento, whose ids are their
# own sequences: 9901xx for setor, and 99xx for segmento (idsegmento is a
# smallint). Both ranges are well past the seed data.
_DEPT_MAPPED = 990101
_DEPT_UNMAPPED = 990102
# ordered by name: the listing sorts a department's segments alphabetically
_SEGMENT_A = (9901, "ZZTest Segmento A")
_SEGMENT_B = (9902, "ZZTest Segmento B")

_VALID_CONFIG = {
    "variables": [{"name": "v1", "field": "age", "operator": ">", "value": "60"}],
    "trigger": "{{v1}}",
    "result": {"level": "high", "message": "Idoso", "description": "Idoso"},
}


@pytest.fixture
def seed_protocols():
    """Insert one global, one demo-owned and one foreign protocol."""
    for id_protocol, schema, name in _ALL_ROWS:
        session.execute(
            text(
                "INSERT INTO public.protocolo "
                "(idprotocolo, schema_name, nome, tp_protocolo, tp_situacao, "
                "configuracao, created_at, created_by) "
                "VALUES (:id, :schema, :name, 2, 1, "
                "CAST(:config AS json), now(), 1)"
            ),
            {
                "id": id_protocol,
                "schema": schema,
                "name": name,
                "config": json.dumps(_VALID_CONFIG),
            },
        )
    session_commit()

    yield

    session.execute(
        text("DELETE FROM public.protocolo WHERE idprotocolo IN :ids").bindparams(
            bindparam("ids", expanding=True)
        ),
        {"ids": list(_ALL_IDS)},
    )
    session_commit()


@pytest.fixture
def seed_departments():
    """Seed setores in demo: one mapped to a segment in two hospitals, one
    mapped to none. Own ids so the test never depends on the seed data."""
    for id_segment, name in (_SEGMENT_A, _SEGMENT_B):
        session.execute(
            text(
                "INSERT INTO demo.segmento (idsegmento, nome, status, cpoe) "
                "VALUES (:id, :name, 1, false)"
            ),
            {"id": id_segment, "name": name},
        )

    for id_hospital, id_department, name in (
        (1, _DEPT_MAPPED, "ZZTest Setor Mapeado"),
        (2, _DEPT_MAPPED, "ZZTest Setor Mapeado (H2)"),
        (1, _DEPT_UNMAPPED, "ZZTest Setor Sem Segmento"),
    ):
        session.execute(
            text(
                "INSERT INTO demo.setor (fkhospital, fksetor, nome) "
                "VALUES (:hospital, :department, :name)"
            ),
            {"hospital": id_hospital, "department": id_department, "name": name},
        )

    for id_segment, id_hospital in ((_SEGMENT_A[0], 1), (_SEGMENT_B[0], 2)):
        session.execute(
            text(
                "INSERT INTO demo.segmentosetor (idsegmento, fkhospital, fksetor) "
                "VALUES (:segment, :hospital, :department)"
            ),
            {
                "segment": id_segment,
                "hospital": id_hospital,
                "department": _DEPT_MAPPED,
            },
        )
    session_commit()

    yield

    session.execute(
        text("DELETE FROM demo.segmentosetor WHERE fksetor IN :ids").bindparams(
            bindparam("ids", expanding=True)
        ),
        {"ids": [_DEPT_MAPPED, _DEPT_UNMAPPED]},
    )
    session.execute(
        text("DELETE FROM demo.setor WHERE fksetor IN :ids").bindparams(
            bindparam("ids", expanding=True)
        ),
        {"ids": [_DEPT_MAPPED, _DEPT_UNMAPPED]},
    )
    session.execute(
        text("DELETE FROM demo.segmento WHERE idsegmento IN :ids").bindparams(
            bindparam("ids", expanding=True)
        ),
        {"ids": [_SEGMENT_A[0], _SEGMENT_B[0]]},
    )
    session_commit()


def _list(client, headers, **params):
    """POST the admin listing and index the result by protocol id."""
    response = client.post(LIST_URL, data=json.dumps(params), headers=headers)

    assert response.status_code == status.HTTP_200_OK

    return {item["id"]: item for item in response.get_json()["data"]}


def _upsert_payload(id_protocol: int, name: str):
    return {
        "id": id_protocol,
        "name": name,
        "protocolType": 2,
        "statusType": 1,
        "config": _VALID_CONFIG,
    }


def test_list_hides_other_schemas_by_default(client, admin_headers, seed_protocols):
    """Without allSchemas only global and own-schema protocols are listed."""
    by_id = _list(client, admin_headers)

    assert _GLOBAL[0] in by_id
    assert _OWN[0] in by_id
    assert _OTHER[0] not in by_id


def test_list_all_schemas_includes_foreign_protocols(
    client, admin_headers, seed_protocols
):
    """allSchemas exposes other schemas' protocols, to be used as copy sources."""
    by_id = _list(client, admin_headers, allSchemas=True)

    assert _OTHER[0] in by_id
    assert by_id[_OTHER[0]]["schema"] == _OTHER[1]
    # the listing only carries the header fields; the config is fetched by id
    assert "config" not in by_id[_OTHER[0]]


def test_list_filters_by_term(client, admin_headers, seed_protocols):
    """The term filter matches the protocol name, case-insensitively."""
    by_id = _list(client, admin_headers, allSchemas=True, term="other schema")

    assert _OTHER[0] in by_id
    assert _GLOBAL[0] not in by_id
    assert _OWN[0] not in by_id


def test_get_returns_the_protocol_with_its_config(
    client, admin_headers, seed_protocols
):
    """The editor loads a single protocol by id, config and schema included."""
    response = client.get(f"{GET_URL}/{_OWN[0]}", headers=admin_headers)

    assert response.status_code == status.HTTP_200_OK

    data = response.get_json()["data"]
    assert data["id"] == _OWN[0]
    assert data["name"] == _OWN[2]
    assert data["schema"] == _OWN[1]
    assert data["config"] == _VALID_CONFIG


def test_get_global_protocol(client, admin_headers, seed_protocols):
    """A global protocol is visible (and editable) from any schema."""
    response = client.get(f"{GET_URL}/{_GLOBAL[0]}", headers=admin_headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["schema"] is None


def test_get_other_schema_protocol_returns_nothing(
    client, admin_headers, seed_protocols
):
    """A protocol owned by another schema is not readable by id."""
    response = client.get(f"{GET_URL}/{_OTHER[0]}", headers=admin_headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] is None


def test_get_other_schema_protocol_with_all_schemas(
    client, admin_headers, seed_protocols
):
    """allSchemas reads a foreign protocol by id, to be used as a copy source."""
    response = client.get(
        f"{GET_URL}/{_OTHER[0]}?allSchemas=true", headers=admin_headers
    )

    assert response.status_code == status.HTTP_200_OK

    data = response.get_json()["data"]
    assert data["schema"] == _OTHER[1]
    assert data["config"] == _VALID_CONFIG


def test_get_unknown_protocol_returns_nothing(client, admin_headers):
    """An id that does not exist is reported the same way as an invisible one."""
    response = client.get(f"{GET_URL}/999999", headers=admin_headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] is None


def test_upsert_global_protocol_keeps_it_global(
    client, admin_headers, seed_protocols
):
    """A global protocol can be edited from any schema and stays global."""
    response = client.post(
        UPSERT_URL,
        data=json.dumps(_upsert_payload(_GLOBAL[0], "ZZAdmin Global Editado")),
        headers=admin_headers,
    )

    assert response.status_code == status.HTTP_200_OK

    edited = _list(client, admin_headers)[_GLOBAL[0]]
    assert edited["name"] == "ZZAdmin Global Editado"
    # editing must not turn a global protocol into a schema-owned one
    assert edited["schema"] is None


def test_upsert_own_schema_protocol(client, admin_headers, seed_protocols):
    """A protocol owned by the current schema can be edited."""
    response = client.post(
        UPSERT_URL,
        data=json.dumps(_upsert_payload(_OWN[0], "ZZAdmin Demo Editado")),
        headers=admin_headers,
    )

    assert response.status_code == status.HTTP_200_OK
    assert _list(client, admin_headers)[_OWN[0]]["name"] == "ZZAdmin Demo Editado"


def test_upsert_persists_only_latest_expire_date(
    client, admin_headers, analyst_headers, seed_protocols
):
    """The flag survives the save and comes back on both read endpoints.

    It is the field that decides whether a protocol firing on an older expire
    date group counts in the prescription summary, so the editor and the
    prescription view must both see the value that was saved."""
    payload = _upsert_payload(_OWN[0], "ZZAdmin Demo Ultimo Grupo")
    payload["config"] = {**_VALID_CONFIG, "onlyLatestExpireDate": True}

    response = client.post(UPSERT_URL, data=json.dumps(payload), headers=admin_headers)

    assert response.status_code == status.HTTP_200_OK

    stored = client.get(f"{GET_URL}/{_OWN[0]}", headers=admin_headers)
    assert stored.get_json()["data"]["config"]["onlyLatestExpireDate"] is True

    described = client.get(f"/protocol/{_OWN[0]}/description", headers=analyst_headers)
    assert described.get_json()["data"]["onlyLatestExpireDate"] is True


def test_upsert_defaults_only_latest_expire_date_to_false(
    client, admin_headers, analyst_headers, seed_protocols
):
    """A config saved without the field keeps counting in the summary from any
    date group"""
    response = client.post(
        UPSERT_URL,
        data=json.dumps(_upsert_payload(_OWN[0], "ZZAdmin Demo Todos Grupos")),
        headers=admin_headers,
    )

    assert response.status_code == status.HTTP_200_OK

    stored = client.get(f"{GET_URL}/{_OWN[0]}", headers=admin_headers)
    assert stored.get_json()["data"]["config"]["onlyLatestExpireDate"] is False

    described = client.get(f"/protocol/{_OWN[0]}/description", headers=analyst_headers)
    assert described.get_json()["data"]["onlyLatestExpireDate"] is False


def test_upsert_other_schema_protocol_is_rejected(
    client, admin_headers, seed_protocols
):
    """A protocol owned by another schema cannot be saved [400]."""
    response = client.post(
        UPSERT_URL,
        data=json.dumps(_upsert_payload(_OTHER[0], "ZZAdmin Invasao")),
        headers=admin_headers,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "schema" in response.get_json()["message"]


def test_department_list_carries_its_segments(client, admin_headers, seed_departments):
    """Each setor is listed once, carrying every segment it belongs to.

    segmentosetor is unique per (fkhospital, fksetor), so a setor only gets
    more than one segment by being mapped in more than one hospital — which
    is exactly what the seeded rows do. The unmapped setor pins that a setor
    without any segment stays in the list: the select must keep offering it.
    """
    response = client.get(DEPARTMENT_LIST_URL, headers=admin_headers)

    assert response.status_code == status.HTTP_200_OK

    departments = response.get_json()["data"]
    ids = [d["idDepartment"] for d in departments]
    assert len(ids) == len(set(ids)), "a setor must not be listed twice"

    by_id = {d["idDepartment"]: d for d in departments}

    mapped = by_id[str(_DEPT_MAPPED)]
    assert mapped["segments"] == [
        {"id": _SEGMENT_A[0], "name": _SEGMENT_A[1]},
        {"id": _SEGMENT_B[0], "name": _SEGMENT_B[1]},
    ]
    assert by_id[str(_DEPT_UNMAPPED)]["segments"] == []
