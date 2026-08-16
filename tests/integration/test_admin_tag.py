"""Integration tests for the /admin/tag endpoints (admin_tag_service).

Covers the permission-aware listing and the upsert rules: name normalisation,
duplicate detection and the restricted path taken by users that only hold
WRITE_PATIENT_TAGS (navigation markers must be prefixed with "NAVEGACAO_").
Rows live in demo.marcador; every name written here starts with a reserved
uppercase prefix so the cleanup never touches seed data.
"""

import json

import pytest
from sqlalchemy import text

from models.enums import TagTypeEnum
from tests.conftest import session, session_commit
from utils import status

LIST_URL = "/admin/tag/list"
UPSERT_URL = "/admin/tag/upsert"

PATIENT = TagTypeEnum.PATIENT.value  # 1
PATIENT_NAV = TagTypeEnum.PATIENT_NAVIGATION.value  # 2

# reserved (uppercase) name space for this module — test_tag.py uses lowercase
# names, and LIKE is case sensitive in PostgreSQL, so the two never collide
_SEEDED_PATIENT = "ZZTEST_ADMIN_PATIENT"
_SEEDED_NAV = "ZZTEST_ADMIN_NAV"

_NEW_PATIENT = "ZZTEST_ADMIN_NEW"
_NEW_NAV = "NAVEGACAO_ZZTEST_ADMIN"

# public.usuario id of the user behind the admin_headers fixture
_ADMIN_USER_ID = 2


def _insert(name: str, tag_type: int, active: bool = True):
    """Insert a marcador row directly, bypassing the endpoint."""
    session.execute(
        text(
            "INSERT INTO demo.marcador "
            "(nome, tp_marcador, ativo, created_at, created_by, updated_at, updated_by) "
            "VALUES (:name, :tp, :active, now(), 1, now(), 1)"
        ),
        {"name": name, "tp": tag_type, "active": active},
    )


def _row(name: str, tag_type: int):
    """Return (ativo, created_by, updated_by) for a marcador row, or None."""
    result = session.execute(
        text(
            "SELECT ativo, created_by, updated_by FROM demo.marcador "
            "WHERE nome = :name AND tp_marcador = :tp"
        ),
        {"name": name, "tp": tag_type},
    )
    return result.first()


def _cleanup():
    """Remove every row this module may have created."""
    session.execute(
        text(
            "DELETE FROM demo.marcador "
            "WHERE nome LIKE 'ZZTEST!_ADMIN%' ESCAPE '!' "
            "OR nome LIKE 'NAVEGACAO!_ZZTEST%' ESCAPE '!'"
        )
    )
    session_commit()


@pytest.fixture(autouse=True)
def seed_tags():
    """Recreate the reserved marcador rows before each test and drop them after."""
    _cleanup()

    _insert(_SEEDED_PATIENT, PATIENT)
    _insert(_SEEDED_NAV, PATIENT_NAV)
    session_commit()

    yield

    _cleanup()


def _list(client, headers, **filters):
    """Call the admin listing endpoint."""
    return client.post(LIST_URL, data=json.dumps(filters), headers=headers)


def _upsert(client, headers, name, tag_type, active=True, new=False):
    """Call the admin upsert endpoint."""
    payload = {"name": name, "tagType": tag_type, "active": active, "new": new}
    return client.post(UPSERT_URL, data=json.dumps(payload), headers=headers)


def _names(response):
    """Extract the set of tag names from a successful response envelope."""
    return {item["name"] for item in response.get_json()["data"]}


def test_list_requires_a_tag_permission(client, navigator_headers):
    """NAVIGATOR may write patient tags but cannot list them here [401 UNAUTHORIZED]."""
    response = _list(client, navigator_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_list_returns_expected_shape(client, admin_headers):
    """A listed tag carries name, tagType, active and both timestamps."""
    response = _list(client, admin_headers)

    assert response.status_code == status.HTTP_200_OK
    items = response.get_json()["data"]
    match = next((item for item in items if item["name"] == _SEEDED_PATIENT), None)
    assert match is not None, f"Tag {_SEEDED_PATIENT} not found in response"
    assert match["tagType"] == PATIENT
    assert match["active"] is True
    assert match["createdAt"] is not None
    assert match["updatedAt"] is not None


def test_list_includes_navigation_tags_with_read_nav(client, admin_headers):
    """With READ_NAV the listing spans patient and navigation markers."""
    response = _list(client, admin_headers)

    assert response.status_code == status.HTTP_200_OK
    names = _names(response)
    assert _SEEDED_PATIENT in names
    assert _SEEDED_NAV in names


def test_list_excludes_navigation_tags_without_read_nav(
    client, config_manager_headers
):
    """Without READ_NAV the listing is restricted to patient markers."""
    response = _list(client, config_manager_headers)

    assert response.status_code == status.HTTP_200_OK
    names = _names(response)
    assert _SEEDED_PATIENT in names
    assert _SEEDED_NAV not in names


def test_list_active_filter(client, admin_headers):
    """The active filter narrows the listing to active markers."""
    _insert("ZZTEST_ADMIN_OFF", PATIENT, active=False)
    session_commit()

    response = _list(client, admin_headers, active=True)

    assert response.status_code == status.HTTP_200_OK
    names = _names(response)
    assert _SEEDED_PATIENT in names
    assert "ZZTEST_ADMIN_OFF" not in names


def test_upsert_requires_a_write_permission(client, viewer_headers):
    """VIEWER holds neither write permission [401 UNAUTHORIZED]."""
    response = _upsert(client, viewer_headers, _NEW_PATIENT, PATIENT)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_upsert_creates_a_tag(client, admin_headers):
    """A new marker is created and returned with its stored attributes."""
    response = _upsert(client, admin_headers, _NEW_PATIENT, PATIENT, new=True)

    assert response.status_code == status.HTTP_200_OK
    data = response.get_json()["data"]
    assert data["name"] == _NEW_PATIENT
    assert data["tagType"] == PATIENT
    assert data["active"] is True

    session_commit()
    row = _row(_NEW_PATIENT, PATIENT)
    assert row is not None
    assert row[0] is True
    assert row[1] == _ADMIN_USER_ID


def test_upsert_uppercases_the_name(client, admin_headers):
    """Names are normalised to uppercase before being stored."""
    response = _upsert(client, admin_headers, _NEW_PATIENT.lower(), PATIENT, new=True)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["name"] == _NEW_PATIENT

    session_commit()
    assert _row(_NEW_PATIENT, PATIENT) is not None


def test_upsert_updates_an_existing_tag(client, admin_headers):
    """Upserting an existing marker updates it instead of duplicating it."""
    response = _upsert(client, admin_headers, _SEEDED_PATIENT, PATIENT, active=False)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["active"] is False

    session_commit()
    row = _row(_SEEDED_PATIENT, PATIENT)
    assert row[0] is False
    # created_by is preserved, updated_by moves to the acting user
    assert row[1] == 1
    assert row[2] == _ADMIN_USER_ID


def test_upsert_rejects_a_duplicate_when_flagged_as_new(client, admin_headers):
    """Creating a marker whose name already exists is refused [400 BAD REQUEST]."""
    response = _upsert(client, admin_headers, _SEEDED_PATIENT, PATIENT, new=True)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"


def test_upsert_same_name_on_another_type_creates_a_new_tag(client, admin_headers):
    """The name/type pair is the identity, so the same name may exist per type."""
    response = _upsert(client, admin_headers, _SEEDED_PATIENT, PATIENT_NAV, new=True)

    assert response.status_code == status.HTTP_200_OK

    session_commit()
    assert _row(_SEEDED_PATIENT, PATIENT) is not None
    assert _row(_SEEDED_PATIENT, PATIENT_NAV) is not None


def test_upsert_rejects_a_name_over_the_limit(client, admin_headers):
    """Names longer than 40 characters are refused [400 BAD REQUEST]."""
    response = _upsert(client, admin_headers, "ZZTEST_ADMIN_" + ("X" * 40), PATIENT)

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_patient_tag_writer_cannot_create_a_patient_tag(client, analyst_headers):
    """WRITE_PATIENT_TAGS alone does not allow writing plain patient markers [403]."""
    response = _upsert(client, analyst_headers, _NEW_PATIENT, PATIENT, new=True)

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.get_json()["code"] == "errors.businessRules"

    session_commit()
    assert _row(_NEW_PATIENT, PATIENT) is None


def test_patient_tag_writer_needs_the_navigation_prefix(client, analyst_headers):
    """A navigation marker created by such a user must start with NAVEGACAO_ [400]."""
    response = _upsert(client, analyst_headers, _NEW_PATIENT, PATIENT_NAV, new=True)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"

    session_commit()
    assert _row(_NEW_PATIENT, PATIENT_NAV) is None


def test_patient_tag_writer_creates_a_prefixed_navigation_tag(client, analyst_headers):
    """With the NAVEGACAO_ prefix the restricted user may create the marker."""
    response = _upsert(client, analyst_headers, _NEW_NAV, PATIENT_NAV, new=True)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["name"] == _NEW_NAV

    session_commit()
    assert _row(_NEW_NAV, PATIENT_NAV) is not None


def test_navigation_prefix_check_is_case_insensitive(client, analyst_headers):
    """The prefix is compared on the uppercased name, so lowercase input passes."""
    response = _upsert(client, analyst_headers, _NEW_NAV.lower(), PATIENT_NAV, new=True)

    assert response.status_code == status.HTTP_200_OK

    session_commit()
    assert _row(_NEW_NAV, PATIENT_NAV) is not None
