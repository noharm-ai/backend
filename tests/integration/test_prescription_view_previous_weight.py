"""Integration tests: the prescription view falls back to the previous weight

GET /prescriptions/<id> states the patient's weight, height and weight date,
and the dose-per-kg alerts and the renal function estimate are computed from
them. When the admission of the prescription has no weight, the view
(prescription_view_service._get_patient_configs) borrows the patient's most
recent weight of the last month, from whichever admission it was taken on,
together with that record's date and height.

test_patient_previous_weight.py pins the lookup itself
(patient_service.get_patient_weight); these tests pin what the screening page
receives:

* the admission's own weight wins, with its own height and date;
* without one, the previous admission's weight, date and height are shown;
* an admission with no patient record at all falls back the same way;
* a weight older than a month is not borrowed: the view states none.

Patients and admissions use the reserved 962000 block (>= 100000, removed by
the session cleanup in tests/conftest.py); the prescriptions use ids of the
same block.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from models.prescription import Patient
from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import create_prescription
from utils import status

PATIENT = 962000
CURRENT_ADMISSION = 962001
PREVIOUS_ADMISSION = 962002
PRESCRIPTION = 962001


def _add_admission(admission_number, weight=None, weight_age_days=None, height=None):
    """Record an admission of the patient, its weight taken
    ``weight_age_days`` ago"""
    patient = Patient()
    patient.admissionNumber = admission_number
    patient.idPatient = PATIENT
    patient.idHospital = 1
    patient.admissionDate = datetime.now() - timedelta(days=60)
    patient.weight = weight
    patient.height = height
    patient.weightDate = (
        datetime.now() - timedelta(days=weight_age_days)
        if weight_age_days is not None
        else None
    )
    session.add(patient)
    session_commit()


@pytest.fixture(autouse=True)
def prescription():
    """A prescription of the current admission, and no admission of the
    patient: every test records the ones it needs"""

    def _delete():
        session.execute(
            text("DELETE FROM demo.prescricao WHERE fkprescricao = :id"),
            {"id": PRESCRIPTION},
        )
        session.execute(
            text("DELETE FROM demo.pessoa WHERE fkpessoa = :id"),
            {"id": PATIENT},
        )
        session_commit()

    _delete()
    create_prescription(
        id=PRESCRIPTION,
        admissionNumber=CURRENT_ADMISSION,
        idPatient=PATIENT,
    )

    yield

    _delete()


def _view(client, headers) -> dict:
    """The prescription view of the test prescription"""
    response = client.get(f"/prescriptions/{PRESCRIPTION}", headers=headers)

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    return response.get_json()["data"]


def _days_ago(iso: str) -> float:
    """How many days before now an ISO date of the view is"""
    return (datetime.now() - datetime.fromisoformat(iso)).total_seconds() / 86400


def test_own_weight_wins_over_a_previous_one(client, analyst_headers):
    """The admission's own weight, height and date are shown even when a more
    recent weight was taken on another admission"""
    _add_admission(CURRENT_ADMISSION, weight=81.0, weight_age_days=5, height=180.0)
    _add_admission(PREVIOUS_ADMISSION, weight=64.0, weight_age_days=1, height=160.0)

    data = _view(client, analyst_headers)

    assert data["weight"] == 81.0
    assert data["height"] == 180.0
    assert 4 < _days_ago(data["weightDate"]) < 6


def test_admission_without_weight_shows_the_previous_one(client, analyst_headers):
    """Without a weight of its own, the view states the previous admission's
    weight, and the date and height of that same record"""
    _add_admission(CURRENT_ADMISSION, weight=None, height=175.0)
    _add_admission(PREVIOUS_ADMISSION, weight=72.5, weight_age_days=3, height=171.0)

    data = _view(client, analyst_headers)

    assert data["weight"] == 72.5
    # the height of the record the weight came from, not the admission's own
    assert data["height"] == 171.0
    assert 2 < _days_ago(data["weightDate"]) < 4


def test_admission_without_patient_record_falls_back_too(client, analyst_headers):
    """An admission whose patient record was not integrated yet still gets
    the patient's previous weight"""
    _add_admission(PREVIOUS_ADMISSION, weight=58.0, weight_age_days=10, height=155.0)

    data = _view(client, analyst_headers)

    assert data["weight"] == 58.0
    assert data["height"] == 155.0
    assert 9 < _days_ago(data["weightDate"]) < 11


def test_weight_older_than_a_month_is_not_borrowed(client, analyst_headers):
    """A weight from more than a month ago is too old: the view states none,
    and keeps the admission's own height"""
    _add_admission(CURRENT_ADMISSION, weight=None, height=175.0)
    _add_admission(PREVIOUS_ADMISSION, weight=90.0, weight_age_days=45, height=171.0)

    data = _view(client, analyst_headers)

    assert data["weight"] is None
    assert data["weightDate"] is None
    assert data["height"] == 175.0
