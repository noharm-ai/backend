import pytest

from models.prescription import PrescriptionClinicalNote
from tests.conftest import session, session_commit

PRESCRIPTION_ID = 20
INVALID_PRESCRIPTION_ID = 999999
URL_BASE = "/prescription-clinical-note"

# Shared state across ordered tests that depend on a created record.
_created_note_id = None


@pytest.mark.order(1)
def test_get_clinical_notes_empty(client, analyst_headers):
    """GET /prescription-clinical-note/<id> — returns 200 with empty list when no notes exist"""
    response = client.get(f"{URL_BASE}/{PRESCRIPTION_ID}", headers=analyst_headers)

    assert response.status_code == 200
    assert response.get_json()["data"] == []


@pytest.mark.order(2)
def test_create_clinical_note(client, analyst_headers):
    """POST /prescription-clinical-note — creates a new note and persists it to the database"""
    global _created_note_id

    payload = {
        "idPrescription": PRESCRIPTION_ID,
        "text": "test clinical note",
        "tpStatus": 0,
    }

    response = client.post(URL_BASE, json=payload, headers=analyst_headers)
    assert response.status_code == 200

    data = response.get_json()["data"]
    _created_note_id = data["id"]

    session.expire_all()
    record = session.get(PrescriptionClinicalNote, _created_note_id)

    assert record is not None
    assert record.idPrescription == PRESCRIPTION_ID
    assert record.text == payload["text"]
    assert record.tpStatus == payload["tpStatus"]
    assert record.createdBy is not None
    assert record.createdAt is not None


@pytest.mark.order(3)
def test_get_clinical_notes_after_create(client, analyst_headers):
    """GET /prescription-clinical-note/<id> — returns the note created in test_create_clinical_note"""
    response = client.get(f"{URL_BASE}/{PRESCRIPTION_ID}", headers=analyst_headers)
    assert response.status_code == 200

    data = response.get_json()["data"]
    assert len(data) >= 1

    ids = [item["id"] for item in data]
    assert _created_note_id in ids


@pytest.mark.order(4)
def test_update_clinical_note(client, analyst_headers):
    """POST /prescription-clinical-note — updates an existing note when id is provided"""
    payload = {
        "id": _created_note_id,
        "idPrescription": PRESCRIPTION_ID,
        "text": "updated clinical note",
        "tpStatus": 0,
    }

    response = client.post(URL_BASE, json=payload, headers=analyst_headers)
    assert response.status_code == 200

    session.expire_all()
    record = session.get(PrescriptionClinicalNote, _created_note_id)

    assert record.text == "updated clinical note"
    assert record.updatedAt is not None


@pytest.mark.order(5)
def test_update_integrated_note_fails(client, analyst_headers):
    """POST /prescription-clinical-note — returns 400 when trying to update an integrated note (tpStatus != 0)"""
    # Mark the record as integrated directly in the DB.
    record = session.get(PrescriptionClinicalNote, _created_note_id)
    record.tpStatus = 1
    session_commit()

    payload = {
        "id": _created_note_id,
        "idPrescription": PRESCRIPTION_ID,
        "text": "should not update",
        "tpStatus": 1,
    }

    response = client.post(URL_BASE, json=payload, headers=analyst_headers)
    assert response.status_code == 400


def test_create_note_invalid_prescription(client, analyst_headers):
    """POST /prescription-clinical-note — returns 400 when idPrescription does not exist"""
    payload = {
        "idPrescription": INVALID_PRESCRIPTION_ID,
        "text": "note for missing prescription",
        "tpStatus": 0,
    }

    response = client.post(URL_BASE, json=payload, headers=analyst_headers)
    assert response.status_code == 400


def test_create_note_permission_denied(client, viewer_headers):
    """POST /prescription-clinical-note — returns 401 for users without WRITE_PRESCRIPTION permission"""
    payload = {
        "idPrescription": PRESCRIPTION_ID,
        "text": "unauthorized note",
        "tpStatus": 0,
    }

    response = client.post(URL_BASE, json=payload, headers=viewer_headers)
    assert response.status_code == 401


def test_get_notes_permission_denied(client, user_manager_headers):
    """GET /prescription-clinical-note/<id> — returns 401 for users without READ_PRESCRIPTION permission"""
    response = client.get(f"{URL_BASE}/{PRESCRIPTION_ID}", headers=user_manager_headers)
    assert response.status_code == 401
