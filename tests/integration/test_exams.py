from unittest.mock import patch

import pytest

from tests.conftest import session

from models.segment import Exams

# Admission / patient present in the seed data (see tests/integration/test_patient.py)
ADMISSION = 5
PATIENT_ID = 5


@pytest.fixture(autouse=True)
def cleanup_manual_exams():
    """Remove exams inserted manually during a test so the suite stays re-runnable.

    Seed exams have created_by = NULL; manually created ones (the only kind these
    tests insert) always set created_by, so deleting those leaves seed data intact.
    """
    yield
    session.query(Exams).filter(
        Exams.admissionNumber == ADMISSION,
        Exams.created_by.isnot(None),
    ).delete(synchronize_session=False)
    session.commit()


def _get_manual_exams():
    """Return the manually inserted exams for the test admission, newest first."""
    return (
        session.query(Exams)
        .filter(
            Exams.admissionNumber == ADMISSION,
            Exams.created_by.isnot(None),
        )
        .all()
    )


def test_create_exam_permission(client, viewer_headers):
    """POST /exams/create - returns 401 for a user without WRITE_PRESCRIPTION"""
    payload = {
        "admissionNumber": ADMISSION,
        "examDate": "2024-01-10T08:00:00",
        "examType": "tgo",
        "result": 42.0,
    }
    response = client.post("/exams/create", json=payload, headers=viewer_headers)

    assert response.status_code == 401
    # nothing should have been persisted
    assert _get_manual_exams() == []


def test_create_exam_persists_record(client, analyst_headers):
    """POST /exams/create - persists the exam with an uppercased type and the author id"""
    payload = {
        "admissionNumber": ADMISSION,
        "examDate": "2024-01-10T08:00:00",
        "examType": "tgo",
        "result": 42.5,
    }

    # the cache refresh talks to Redis; it is out of scope for this test
    with patch("services.exams_service.refresh_exams_cache") as refresh_mock:
        response = client.post("/exams/create", json=payload, headers=analyst_headers)

    assert response.status_code == 200
    refresh_mock.assert_called_once()

    session.expire_all()
    exams = _get_manual_exams()
    assert len(exams) == 1

    exam = exams[0]
    assert exam.idPatient == PATIENT_ID
    assert exam.admissionNumber == ADMISSION
    assert exam.typeExam == "TGO"  # stored uppercased
    assert exam.value == 42.5
    assert exam.created_by == 1  # demo user


def test_create_exam_unknown_admission_returns_400(client, analyst_headers):
    """POST /exams/create - returns 400 when the admission does not exist"""
    payload = {
        "admissionNumber": 999999999,
        "examDate": "2024-01-10T08:00:00",
        "examType": "tgo",
        "result": 10.0,
    }

    with patch("services.exams_service.refresh_exams_cache") as refresh_mock:
        response = client.post("/exams/create", json=payload, headers=analyst_headers)

    assert response.status_code == 400
    refresh_mock.assert_not_called()
    assert _get_manual_exams() == []


def test_create_exam_multiple_persists_all_entries(client, analyst_headers):
    """POST /exams/create-multiple - persists every entry in the batch"""
    payload = {
        "admissionNumber": ADMISSION,
        "exams": [
            {"examDate": "2024-01-10T08:00:00", "examType": "tgo", "result": 30.0},
            {"examDate": "2024-01-10T08:00:00", "examType": "tgp", "result": 55.0},
        ],
    }

    with patch("services.exams_service.refresh_exams_cache"):
        response = client.post(
            "/exams/create-multiple", json=payload, headers=analyst_headers
        )

    assert response.status_code == 200

    session.expire_all()
    exams = _get_manual_exams()
    assert len(exams) == 2
    stored = {(e.typeExam, e.value) for e in exams}
    assert stored == {("TGO", 30.0), ("TGP", 55.0)}


def test_delete_unknown_exam_returns_400(client, analyst_headers):
    """POST /exams/delete - returns 400 when the exam does not exist"""
    payload = {"admissionNumber": ADMISSION, "idExam": 999999999999}
    response = client.post("/exams/delete", json=payload, headers=analyst_headers)

    assert response.status_code == 400


def test_list_exam_types_returns_list(client, analyst_headers):
    """GET /exams/types/list - returns a 200 with a list payload"""
    response = client.get("/exams/types/list", headers=analyst_headers)

    assert response.status_code == 200
    assert isinstance(response.get_json()["data"], list)
