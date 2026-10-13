"""Integration tests for patient_service.get_patient_weight.

When the current admission has no weight, the prescription screen, the exams
panel, the clinical-note data and the antimicrobial timeline all fall back to
the patient's *previous* weight: the most recent weight recorded for the same
patient in the last month, whichever admission it was taken on. Dose-per-kg
alerts and the renal function estimate are computed from it, so picking the
wrong row is a clinical error, not a cosmetic one. The rules pinned here:

* the lookup is by patient, so a weight taken on another admission counts;
* the most recent weight wins, and its date and height come from the same row;
* an admission without a weight is skipped even when it is the newest one;
* a weight older than one month is too old to be trusted, so none is returned;
* another patient's weight is never borrowed.

The query had no coverage. Patients use the reserved ``>= 100000`` admission
range (961000 block), which the session cleanup in ``tests/conftest.py``
removes as well.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from mobile import app as flask_app
from models.main import db
from models.prescription import Patient
from services import patient_service
from tests.conftest import session, session_commit

PATIENT = 961000
OTHER_PATIENT = 961001
ADMISSION_BASE = 961000


@contextmanager
def _demo_schema():
    """Give the service session the demo schema, then throw the session away."""
    with flask_app.app_context():
        db.session.connection(
            execution_options={"schema_translate_map": {None: "demo"}}
        )
        try:
            yield
        finally:
            db.session.rollback()
            db.session.remove()


def _previous_weight(id_patient):
    """Look up the previous weight the way the prescription screen does."""
    with _demo_schema():
        return patient_service.get_patient_weight(id_patient)


def _add_admission(offset, id_patient, weight, weight_age_days, height=None):
    """Record an admission whose weight was taken ``weight_age_days`` ago."""
    patient = Patient()
    patient.admissionNumber = ADMISSION_BASE + offset
    patient.idPatient = id_patient
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
def clean_patients():
    """Start and finish every test without this module's admissions."""

    def _delete():
        session.execute(
            text("DELETE FROM demo.pessoa WHERE fkpessoa IN (:patient, :other)"),
            {"patient": PATIENT, "other": OTHER_PATIENT},
        )
        session_commit()

    _delete()
    yield
    _delete()


def test_patient_without_admissions_has_no_previous_weight():
    """A patient never seen has nothing to fall back to."""
    assert _previous_weight(PATIENT) is None


def test_most_recent_weight_of_any_admission_is_used():
    """Every admission of the patient counts, and the newest weight wins."""
    _add_admission(1, PATIENT, weight=70.0, weight_age_days=20, height=170.0)
    _add_admission(2, PATIENT, weight=68.5, weight_age_days=3, height=171.0)
    _add_admission(3, PATIENT, weight=72.0, weight_age_days=10, height=169.0)

    result = _previous_weight(PATIENT)

    assert result.weight == 68.5
    # date and height come from the same record as the weight
    assert result.height == 171.0
    assert datetime.now() - result.weightDate < timedelta(days=4)


def test_admission_without_weight_is_skipped():
    """A newer admission with no weight does not hide an older weight."""
    _add_admission(1, PATIENT, weight=80.0, weight_age_days=15)
    _add_admission(2, PATIENT, weight=None, weight_age_days=1)

    result = _previous_weight(PATIENT)

    assert result.weight == 80.0


def test_weight_older_than_one_month_is_ignored():
    """A weight from more than a month ago is too old to be trusted."""
    _add_admission(1, PATIENT, weight=65.0, weight_age_days=45)

    assert _previous_weight(PATIENT) is None


def test_old_weight_does_not_beat_a_recent_one():
    """Only the weights inside the window compete for the most recent."""
    _add_admission(1, PATIENT, weight=90.0, weight_age_days=40)
    _add_admission(2, PATIENT, weight=88.0, weight_age_days=25)

    assert _previous_weight(PATIENT).weight == 88.0


def test_another_patients_weight_is_never_borrowed():
    """The lookup is scoped to the patient, even when theirs is missing."""
    _add_admission(1, OTHER_PATIENT, weight=55.0, weight_age_days=2)

    assert _previous_weight(PATIENT) is None
    assert _previous_weight(OTHER_PATIENT).weight == 55.0
