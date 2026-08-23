"""Integration tests for patient tags and the observation history.

Covers the tag branch of POST /patient/<admissionNumber>
(patient_service.save_patient / patient_service._get_tags) and
GET /patient/<admissionNumber>/observation-history.

Tag rules exercised here:
  * names are stored uppercased;
  * at most 10 tags per patient;
  * an unknown name creates a marcador row, typed by the caller's role;
  * a navigator may only create tags prefixed with NAVEGACAO_;
  * a caller without READ_NAV keeps the navigation tags already on the patient.
"""

from datetime import datetime

import pytest
from sqlalchemy import text

from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import create_prescription

from models.enums import TagTypeEnum
from models.prescription import Patient

# outside the ranges used by the shared counters, inside the cleanup range
ADMISSION = 991001
PRESCRIPTION = 991010

TAG_EXISTING = "ZZTEST_PAT_EXISTING"
TAG_NEW = "ZZTEST_PAT_NEW"
TAG_NAV = "NAVEGACAO_ZZTESTPAT"
TAG_PREFIX = "ZZTEST_PAT"


@pytest.fixture
def patient():
    """Create a patient with one prescription and drop every trace afterwards."""
    create_prescription(
        id=PRESCRIPTION,
        admissionNumber=ADMISSION,
        idPatient=1,
        date=datetime.now(),
    )

    p = Patient()
    p.admissionNumber = ADMISSION
    p.idPatient = 1
    p.idHospital = 1
    p.admissionDate = datetime.now()
    session.add(p)

    session.execute(
        text(
            "INSERT INTO demo.marcador "
            "(nome, tp_marcador, ativo, created_at, created_by) "
            "VALUES (:nome, :tp, true, now(), 1)"
        ),
        {"nome": TAG_EXISTING, "tp": TagTypeEnum.PATIENT.value},
    )
    session_commit()

    yield p

    session.execute(
        text("DELETE FROM demo.pessoa_audit WHERE nratendimento = :admission"),
        {"admission": ADMISSION},
    )
    session.execute(
        text("DELETE FROM demo.pessoa WHERE nratendimento = :admission"),
        {"admission": ADMISSION},
    )
    session.execute(
        text("DELETE FROM demo.prescricao WHERE fkprescricao = :id"),
        {"id": PRESCRIPTION},
    )
    session.execute(
        text(
            "DELETE FROM demo.marcador "
            "WHERE nome LIKE :patient_prefix OR nome LIKE :nav_prefix"
        ),
        {"patient_prefix": f"{TAG_PREFIX}%", "nav_prefix": f"{TAG_NAV}%"},
    )
    session_commit()


def _save(client, headers, data):
    """POST the given payload to the patient endpoint."""
    return client.post(f"/patient/{ADMISSION}", json=data, headers=headers)


def _stored_tags():
    """Read the tags currently persisted for the patient."""
    session.expire_all()
    return session.get(Patient, ADMISSION).tags


def _tag_type(name):
    """Return the marcador type stored for a tag name, or None when absent."""
    row = session.execute(
        text("SELECT tp_marcador FROM demo.marcador WHERE nome = :nome"),
        {"nome": name},
    ).first()

    return row[0] if row else None


def test_save_tags_permission_denied(client, viewer_headers, patient):
    """A viewer cannot write patient tags [401 UNAUTHORIZED]."""
    response = _save(client, viewer_headers, {"tags": [TAG_NEW]})

    assert response.status_code == 401
    assert _stored_tags() is None


def test_save_tags_uppercases_and_persists(client, analyst_headers, patient):
    """Tags are stored uppercased [200 OK]."""
    response = _save(client, analyst_headers, {"tags": [TAG_EXISTING.lower()]})

    assert response.status_code == 200
    assert _stored_tags() == [TAG_EXISTING]


def test_save_tags_creates_missing_tag(client, analyst_headers, patient):
    """An unknown tag is registered as a regular patient tag."""
    response = _save(client, analyst_headers, {"tags": [TAG_EXISTING, TAG_NEW]})

    assert response.status_code == 200
    assert _stored_tags() == [TAG_EXISTING, TAG_NEW]
    assert _tag_type(TAG_NEW) == TagTypeEnum.PATIENT.value


def test_save_tags_empty_list_clears_tags(client, analyst_headers, patient):
    """An empty list removes the tags instead of storing an empty array."""
    assert _save(client, analyst_headers, {"tags": [TAG_EXISTING]}).status_code == 200

    response = _save(client, analyst_headers, {"tags": []})

    assert response.status_code == 200
    assert _stored_tags() is None


def test_save_tags_above_limit(client, analyst_headers, patient):
    """More than 10 tags is rejected [400 BAD REQUEST]."""
    tags = [f"{TAG_PREFIX}_{i:02d}" for i in range(11)]
    response = _save(client, analyst_headers, {"tags": tags})

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.businessRules"
    assert _stored_tags() is None


def test_save_tags_name_too_long(client, analyst_headers, patient):
    """A tag longer than the 40 char limit is rejected [400 BAD REQUEST]."""
    response = _save(client, analyst_headers, {"tags": ["Z" * 41]})

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.businessRules"


def test_save_tags_name_too_short(client, analyst_headers, patient):
    """A tag shorter than 3 chars is rejected [400 BAD REQUEST]."""
    response = _save(client, analyst_headers, {"tags": ["ZZ"]})

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.businessRules"


def test_navigator_tag_requires_prefix(client, navigator_headers, patient):
    """A navigator creating a tag without the NAVEGACAO_ prefix is rejected."""
    response = _save(client, navigator_headers, {"tags": [TAG_NEW]})

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.businessRules"
    assert _tag_type(TAG_NEW) is None


def test_navigator_tag_with_prefix_is_navigation_type(
    client, navigator_headers, patient
):
    """A navigator's new tag is registered as a navigation tag [200 OK]."""
    response = _save(client, navigator_headers, {"tags": [TAG_NAV]})

    assert response.status_code == 200
    assert _stored_tags() == [TAG_NAV]
    assert _tag_type(TAG_NAV) == TagTypeEnum.PATIENT_NAVIGATION.value


def test_non_navigator_keeps_navigation_tags(
    client, analyst_headers, navigator_headers, patient
):
    """A caller without READ_NAV cannot drop the navigation tags already set."""
    assert _save(client, navigator_headers, {"tags": [TAG_NAV]}).status_code == 200

    response = _save(client, analyst_headers, {"tags": [TAG_EXISTING]})

    assert response.status_code == 200
    assert _stored_tags() == [TAG_EXISTING, TAG_NAV]


def test_save_name_without_permission(client, analyst_headers, patient):
    """Editing the patient name requires WRITE_NAME [401 UNAUTHORIZED]."""
    response = _save(client, analyst_headers, {"name": {"name": "zztest"}})

    assert response.status_code == 401


def test_observation_history_permission_denied(client, navigator_headers, patient):
    """The observation history requires READ_PRESCRIPTION [401 UNAUTHORIZED]."""
    response = client.get(
        f"/patient/{ADMISSION}/observation-history", headers=navigator_headers
    )

    assert response.status_code == 401


def test_observation_history_records_changes(client, analyst_headers, patient):
    """Each observation change is recorded once and returned newest first."""
    assert _save(client, analyst_headers, {"observation": "first"}).status_code == 200
    # saving the same text again must not create another record
    assert _save(client, analyst_headers, {"observation": "first"}).status_code == 200
    assert _save(client, analyst_headers, {"observation": "second"}).status_code == 200

    response = client.get(
        f"/patient/{ADMISSION}/observation-history", headers=analyst_headers
    )
    data = response.get_json()["data"]

    assert response.status_code == 200
    assert [item["text"] for item in data] == ["second", "first"]
    assert all(item["createdAt"] for item in data)
    assert all(item["createdBy"] for item in data)


def test_observation_history_empty(client, analyst_headers, patient):
    """A patient with no observation change has an empty history [200 OK]."""
    response = client.get(
        f"/patient/{ADMISSION}/observation-history", headers=analyst_headers
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == []
