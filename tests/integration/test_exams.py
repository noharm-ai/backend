from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import bindparam, text

from models.segment import Exams
from tests.conftest import session, session_commit

# Admission / patient present in the seed data (see tests/integration/test_patient.py)
ADMISSION = 5
PATIENT_ID = 5
SEGMENT = 1


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


# Two exam types configured as creatinina. "ACR" sorts before "ZCR", so the older
# one is reached first when the exam list is walked (it is sorted by type, not date).
OLD_CREATININA_TYPE = "ACR"
NEW_CREATININA_TYPE = "ZCR"
OLD_CREATININA_DATE = datetime.today() - timedelta(days=10)
NEW_CREATININA_DATE = datetime.today() - timedelta(days=1)
CREATININA_EXAM_IDS = [900001, 900002]
CREATININA_EXAM_TYPES = [
    OLD_CREATININA_TYPE.lower(),
    NEW_CREATININA_TYPE.lower(),
    "mdrd",
]


def _add_seg_exam(type_exam: str, initials: str, name: str, order: int):
    """Configure an exam type for the test segment"""
    session.execute(
        text(
            "INSERT INTO demo.segmentoexame "
            "(idsegmento, tpexame, abrev, nome, min, max, referencia, posicao, ativo, update_by) "
            "VALUES (:seg, :tp, :abrev, :name, 0, 2, '', :order, true, 1)"
        ),
        {
            "seg": SEGMENT,
            "tp": type_exam.lower(),
            "abrev": initials,
            "name": name,
            "order": order,
        },
    )


def _add_exam(id_exam: int, type_exam: str, exam_date: datetime, value: float):
    """Add a result for the test patient"""
    session.execute(
        text(
            "INSERT INTO demo.exame "
            "(fkexame, fkpessoa, nratendimento, dtexame, tpexame, resultado, unidade) "
            "VALUES (:id, :patient, :admission, :date, :tp, :value, 'mg/dL')"
        ),
        {
            "id": id_exam,
            "patient": PATIENT_ID,
            "admission": ADMISSION,
            "date": exam_date,
            "tp": type_exam,
            "value": value,
        },
    )


def _clean_creatinina_setup():
    """Remove the exam types and results created by the creatinina fixtures"""
    session.execute(
        text("DELETE FROM demo.exame WHERE fkexame IN :ids").bindparams(
            bindparam("ids", expanding=True)
        ),
        {"ids": CREATININA_EXAM_IDS},
    )
    session.execute(
        text(
            "DELETE FROM demo.segmentoexame "
            "WHERE idsegmento = :seg AND tpexame IN :types"
        ).bindparams(bindparam("types", expanding=True)),
        {"seg": SEGMENT, "types": CREATININA_EXAM_TYPES},
    )
    session_commit()


@pytest.fixture
def two_creatinina_types():
    """Two exam types configured as creatinina (plus mdrd), one result of each."""
    _clean_creatinina_setup()

    _add_seg_exam(OLD_CREATININA_TYPE, "creatinina", "Creatinina", 1)
    _add_seg_exam(NEW_CREATININA_TYPE, "creatinina", "Creatinina", 2)
    _add_seg_exam("mdrd", "MDRD", "MDRD", 3)

    _add_exam(CREATININA_EXAM_IDS[0], OLD_CREATININA_TYPE, OLD_CREATININA_DATE, 1.0)
    _add_exam(CREATININA_EXAM_IDS[1], NEW_CREATININA_TYPE, NEW_CREATININA_DATE, 3.0)
    session_commit()

    yield

    _clean_creatinina_setup()


@pytest.fixture
def padded_creatinina_initials():
    """A single creatinina exam type whose initials carry trailing whitespace."""
    _clean_creatinina_setup()

    _add_seg_exam(NEW_CREATININA_TYPE, "creatinina ", "Creatinina", 1)
    _add_seg_exam("mdrd", "MDRD", "MDRD", 2)

    _add_exam(CREATININA_EXAM_IDS[1], NEW_CREATININA_TYPE, NEW_CREATININA_DATE, 3.0)
    session_commit()

    yield

    _clean_creatinina_setup()


def test_exams_by_admission_uses_most_recent_creatinina(
    client, analyst_headers, two_creatinina_types
):
    """GET /exams/<admission> - renal calc uses the most recent creatinina, not the first exam type"""
    response = client.get(
        f"/exams/{ADMISSION}?idSegment={SEGMENT}", headers=analyst_headers
    )

    assert response.status_code == 200
    data = response.get_json()["data"]

    # both creatinina types are still reported individually
    assert data[OLD_CREATININA_TYPE.lower()]["value"] == 1.0
    assert data[NEW_CREATININA_TYPE.lower()]["value"] == 3.0

    # the derived calculation must be based on the most recent one
    assert data["mdrd"]["date"] == NEW_CREATININA_DATE.isoformat()


def test_exams_by_admission_creatinina_initials_are_trimmed(
    client, analyst_headers, padded_creatinina_initials
):
    """GET /exams/<admission> - renal calc runs even when the creatinina initials are padded"""
    response = client.get(
        f"/exams/{ADMISSION}?idSegment={SEGMENT}", headers=analyst_headers
    )

    assert response.status_code == 200
    data = response.get_json()["data"]

    assert "mdrd" in data
    assert data["mdrd"]["date"] == NEW_CREATININA_DATE.isoformat()
