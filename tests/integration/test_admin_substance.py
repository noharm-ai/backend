"""Integration tests for the /admin/substance endpoints (admin_substance_service).

Covers the listing filters, the single-substance lookup and the upsert
business rules. Rows live in the shared public.substancia / public.classe
tables; the 95000+ sctid range is reserved for this module.
"""

import json

import pytest
from sqlalchemy import text

from tests.conftest import session, session_commit
from tests.utils.utils_test_admin_substance import (
    create_test_substance,
    create_test_substance_class,
    get_substance_row,
    set_substance_handling,
)
from utils import status

LIST_URL = "/admin/substance/list"
GET_URL = "/admin/substance"
UPSERT_URL = "/admin/substance"

# sctid range reserved for this module (>= 90000 so the session-wide cleanup in
# tests/conftest.py also catches leftovers, but clear of the unit-conversion ids)
_ALPHA = 95001
_BETA = 95002
_GAMMA = 95003
_NEW = 95010
_EXISTING_TO_UPDATE = 95011

_ALL_SEEDED = (_ALPHA, _BETA, _GAMMA)
_ALL_UPSERTED = (_NEW, _EXISTING_TO_UPDATE)

_CLASS_A = "ZZTA"
_CLASS_B = "ZZTB"

# every seeded substance name starts with this, so a single ilike isolates them
_NAME_PREFIX = "ZZTest Subs"


@pytest.fixture(scope="module", autouse=True)
def seed_substances():
    """Create the classes and substances this module filters over."""
    create_test_substance_class(_CLASS_A, "ZZTest Class A")
    create_test_substance_class(_CLASS_B, "ZZTest Class B")

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
    # Beta: unclassified, active, no curation, no max dose, handling filled
    create_test_substance(
        id=_BETA,
        name="ZZTest Subs Beta",
        active=True,
        tags=["zzt-shared"],
        updated_by=1,
    )
    set_substance_handling(_BETA, json.dumps({"chemo": "S"}))
    # Gamma: classified, inactive, max dose (pediatric weight) + default unit
    create_test_substance(
        id=_GAMMA,
        name="ZZTest Subs Gamma",
        id_class=_CLASS_B,
        active=False,
        default_measureunit="mg",
        maxdose_pediatric_weight=5,
        updated_by=1,
    )

    yield

    _delete_substances(_ALL_SEEDED + _ALL_UPSERTED)
    session.execute(
        text("DELETE FROM public.classe WHERE idclasse IN :ids").bindparams(
            ids=(_CLASS_A, _CLASS_B)
        )
    )
    session_commit()


@pytest.fixture
def substance_to_update():
    """A substance that already exists, so upsert takes the update path."""
    create_test_substance(
        id=_EXISTING_TO_UPDATE,
        name="ZZTest Subs Existing",
        id_class=_CLASS_A,
        active=True,
        default_measureunit="mg",
        maxdose_adult=10,
        updated_by=1,
    )
    yield _EXISTING_TO_UPDATE
    _delete_substances((_EXISTING_TO_UPDATE,))


@pytest.fixture
def cleanup_new_substance():
    """Remove the substance created by the insert path of upsert."""
    yield _NEW
    _delete_substances((_NEW,))


def _delete_substances(ids):
    session.execute(
        text("DELETE FROM public.substancia WHERE sctid IN :ids").bindparams(ids=tuple(ids))
    )
    session_commit()


def _list(client, headers, **filters):
    """POST the listing endpoint, always narrowed to this module's substances."""
    payload = {"name": f"{_NAME_PREFIX}%", "limit": 50, "offset": 0}
    payload.update(filters)

    return client.post(LIST_URL, data=json.dumps(payload), headers=headers)


def _result(response):
    """The service payload of a listing response ({count, data})."""
    return response.get_json()["data"]


def _ids(response):
    """Substance ids of a listing response, in the order returned."""
    return [item["id"] for item in _result(response)["data"]]


def _upsert_payload(**overrides):
    payload = {"id": _NEW, "name": "ZZTest Subs Upserted", "active": True}
    payload.update(overrides)

    return payload


def test_list_returns_substances_ordered_by_name(client, admin_headers):
    """List: substances come back ordered by name with the total count"""
    response = _list(client, admin_headers)

    assert response.status_code == status.HTTP_200_OK
    result = _result(response)
    data = result["data"]
    assert _ids(response) == [str(_ALPHA), str(_BETA), str(_GAMMA)]
    assert result["count"] == 3
    assert data[0]["name"] == "ZZTest Subs Alpha"
    assert data[0]["className"] == "ZZTest Class A"
    assert data[0]["responsible"] == "Demonstração"
    # an unclassified substance reports no class instead of failing the join
    assert data[1]["className"] is None


def test_list_without_matches_returns_empty_result(client, admin_headers):
    """List: a filter matching nothing returns count 0 and no data"""
    response = _list(client, admin_headers, name="ZZTest Subs Nonexistent%")

    assert response.status_code == status.HTTP_200_OK
    assert _result(response) == {"count": 0, "data": []}


def test_list_count_ignores_pagination(client, admin_headers):
    """List: count reflects every match while data honors limit and offset"""
    response = _list(client, admin_headers, limit=1, offset=1)

    assert response.status_code == status.HTTP_200_OK
    assert _result(response)["count"] == 3
    assert _ids(response) == [str(_BETA)]


def test_list_filters_by_class_list(client, admin_headers):
    """List: idClassList keeps only substances of the given classes"""
    response = _list(client, admin_headers, idClassList=[_CLASS_B])

    assert _ids(response) == [str(_GAMMA)]


def test_list_filters_by_class_name(client, admin_headers):
    """List: className matches the class id"""
    response = _list(client, admin_headers, className=_CLASS_A)

    assert _ids(response) == [str(_ALPHA)]


@pytest.mark.parametrize(
    "has_class,expected",
    [(True, [str(_ALPHA), str(_GAMMA)]), (False, [str(_BETA)])],
)
def test_list_filters_by_presence_of_class(client, admin_headers, has_class, expected):
    """List: hasClass splits classified from unclassified substances"""
    response = _list(client, admin_headers, hasClass=has_class)

    assert _ids(response) == expected


@pytest.mark.parametrize(
    "has_admin_text,expected",
    [(True, [str(_ALPHA)]), (False, [str(_BETA), str(_GAMMA)])],
)
def test_list_filters_by_presence_of_admin_text(
    client, admin_headers, has_admin_text, expected
):
    """List: hasAdminText splits curated from uncurated substances"""
    response = _list(client, admin_headers, hasAdminText=has_admin_text)

    assert _ids(response) == expected


def test_list_filters_by_presence_of_max_dose(client, admin_headers):
    """List: each max dose filter looks at its own column"""
    adult = _list(client, admin_headers, hasMaxDoseAdult=True)
    assert _ids(adult) == [str(_ALPHA)]

    pediatric_weight = _list(client, admin_headers, hasMaxDosePediatricWeight=True)
    assert _ids(pediatric_weight) == [str(_GAMMA)]

    # Alpha carries an adult dose only, so the weight variants exclude it
    adult_weight = _list(client, admin_headers, hasMaxDoseAdultWeight=True)
    assert _ids(adult_weight) == []

    pediatric = _list(client, admin_headers, hasMaxDosePediatric=True)
    assert _ids(pediatric) == []


def test_list_filters_by_active_flag(client, admin_headers):
    """List: active filters out substances with the opposite flag"""
    actives = _list(client, admin_headers, active=True)
    assert _ids(actives) == [str(_ALPHA), str(_BETA)]

    inactives = _list(client, admin_headers, active=False)
    assert _ids(inactives) == [str(_GAMMA)]


def test_list_filters_by_tags_overlap(client, admin_headers):
    """List: tags keeps substances sharing at least one of the given tags"""
    response = _list(client, admin_headers, tags=["zzt-alpha"])
    assert _ids(response) == [str(_ALPHA)]

    shared = _list(client, admin_headers, tags=["zzt-shared"])
    assert _ids(shared) == [str(_ALPHA), str(_BETA)]


def test_list_filters_by_tags_not_in(client, admin_headers):
    """List: tpSubstanceTagList=notin excludes substances carrying the tags"""
    response = _list(
        client, admin_headers, tags=["zzt-alpha"], tpSubstanceTagList="notin"
    )

    # Gamma has no tags at all, and coalesce treats that as an empty array
    assert _ids(response) == [str(_BETA), str(_GAMMA)]


def test_list_filters_by_handling_filled_and_empty(client, admin_headers):
    """List: handlingOption switches between filled and empty handling keys"""
    filled = _list(
        client, admin_headers, handlingTypeList=["chemo"], handlingOption="filled"
    )
    assert _ids(filled) == [str(_BETA)]

    empty = _list(
        client, admin_headers, handlingTypeList=["chemo"], handlingOption="empty"
    )
    assert _ids(empty) == [str(_ALPHA), str(_GAMMA)]


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


def test_upsert_creates_a_new_substance(client, admin_headers, cleanup_new_substance):
    """Upsert: an unknown id inserts the substance and echoes it back"""
    payload = _upsert_payload(
        idClass=_CLASS_A,
        adminText="new text",
        defaultMeasureUnit="mg",
        maxdoseAdult=250,
        tags=["zzt-new"],
        divisionRange=0.5,
        handling={"chemo": "S"},
    )

    response = client.post(UPSERT_URL, data=json.dumps(payload), headers=admin_headers)

    assert response.status_code == status.HTTP_200_OK
    data = response.get_json()["data"]
    assert data["id"] == str(_NEW)
    assert data["name"] == "ZZTest Subs Upserted"
    assert data["className"] == "ZZTest Class A"
    assert data["maxdoseAdult"] == 250
    assert data["divisionRange"] == 0.5
    assert data["handling"] == {"chemo": "S"}

    row = get_substance_row(_NEW)
    assert row is not None
    assert row.nome == "ZZTest Subs Upserted"
    assert row.idclasse == _CLASS_A
    assert row.divisor_faixa == 0.5


def test_upsert_updates_an_existing_substance(
    client, admin_headers, substance_to_update
):
    """Upsert: a known id overwrites the stored attributes"""
    payload = _upsert_payload(
        id=substance_to_update,
        name="ZZTest Subs Renamed",
        active=False,
        idClass=_CLASS_B,
        defaultMeasureUnit="ml",
        maxdoseAdult=42,
    )

    response = client.post(UPSERT_URL, data=json.dumps(payload), headers=admin_headers)

    assert response.status_code == status.HTTP_200_OK
    data = response.get_json()["data"]
    assert data["name"] == "ZZTest Subs Renamed"
    assert data["active"] is False
    assert data["className"] == "ZZTest Class B"

    row = get_substance_row(substance_to_update)
    assert row.nome == "ZZTest Subs Renamed"
    assert row.ativo is False
    assert row.unidadepadrao == "ml"
    assert row.dosemax_adulto == 42


def test_upsert_stamps_the_requesting_user_as_responsible(
    client, admin_headers, substance_to_update
):
    """Upsert: the substance records who last changed it"""
    payload = _upsert_payload(
        id=substance_to_update,
        name="ZZTest Subs Existing",
        defaultMeasureUnit="mg",
        maxdoseAdult=10,
    )

    response = client.post(UPSERT_URL, data=json.dumps(payload), headers=admin_headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["responsible"] == "User Admin"
    assert get_substance_row(substance_to_update).update_by == 2


def test_upsert_clears_empty_handling(
    client, admin_headers, cleanup_new_substance
):
    """Upsert: an empty handling object is stored as null instead of {}"""
    payload = _upsert_payload(handling={})

    response = client.post(UPSERT_URL, data=json.dumps(payload), headers=admin_headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["handling"] is None
    assert get_substance_row(_NEW).manejo is None


@pytest.mark.parametrize(
    "dose_field",
    [
        "maxdoseAdult",
        "maxdoseAdultWeight",
        "maxdosePediatric",
        "maxdosePediatricWeight",
    ],
)
def test_upsert_rejects_max_dose_without_default_measure_unit(
    client, admin_headers, cleanup_new_substance, dose_field
):
    """Upsert: any max dose requires a default measure unit"""
    payload = _upsert_payload(**{dose_field: 10})

    response = client.post(UPSERT_URL, data=json.dumps(payload), headers=admin_headers)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"
    # the rejected insert must not leak into the table
    assert get_substance_row(_NEW) is None


def test_upsert_rejects_payload_without_required_fields(client, admin_headers):
    """Upsert: a payload missing name fails pydantic validation"""
    response = client.post(
        UPSERT_URL, data=json.dumps({"id": _NEW, "active": True}), headers=admin_headers
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["message"] == "Parâmetros inválidos"


def test_list_requires_the_admin_substances_permission(client, analyst_headers):
    """List: a role without ADMIN_SUBSTANCES is rejected"""
    response = _list(client, analyst_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_get_requires_the_admin_substances_permission(client, analyst_headers):
    """Get: a role without ADMIN_SUBSTANCES is rejected"""
    response = client.get(f"{GET_URL}/{_ALPHA}", headers=analyst_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_upsert_requires_the_admin_substances_permission(client, analyst_headers):
    """Upsert: a role without ADMIN_SUBSTANCES is rejected"""
    response = client.post(
        UPSERT_URL, data=json.dumps(_upsert_payload()), headers=analyst_headers
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert get_substance_row(_NEW) is None


def test_curator_can_manage_substances(client, curator_headers):
    """List: the curator role also holds ADMIN_SUBSTANCES"""
    response = _list(client, curator_headers)

    assert response.status_code == status.HTTP_200_OK
    assert _ids(response) == [str(_ALPHA), str(_BETA), str(_GAMMA)]
