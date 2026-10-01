"""Integration tests for POST /patient/<admissionNumber> (patient_service.save_patient).

The endpoint is the single write path for the patient record the whole
screening relies on: body weight and height (which feed the dose-per-kg and
renal-function calculations), pregnancy/lactation/dialysis flags (which gate
their own alerts), the free-text clinical alert shown on the prescription,
the observation note, and the discharge date.

What is exercised here:
  * which fields each permission may write — WRITE_PRESCRIPTION for the
    clinical data, ADMIN_PATIENT/READ_NAV for the discharge date,
    WRITE_NAME for the patient name;
  * the weight bookkeeping: a changed weight stamps `dtpeso` and asks the
    caller to recalculate the prescription, an unchanged one does not;
  * the clinical alert, which is only stored together with an expiry date;
  * the audit trail: every save records an UPSERT, and a changed observation
    records an extra OBSERVATION_RECORD carrying the new text;
  * the implicit creation of the patient row from the first prescription of
    the admission, and the error raised when there is no prescription.

Tag handling, which shares this endpoint, is covered by test_patient_tags.py.
"""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import text

from models.enums import PatientAuditTypeEnum
from models.prescription import Patient, PatientAudit
from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import create_prescription

# outside the ranges used by the shared counters, inside the cleanup range
ADMISSION = 991501
PRESCRIPTION = 991510

# admission used by the tests that exercise the implicit patient creation
ORPHAN_ADMISSION = 991502
ORPHAN_PRESCRIPTION = 991520

# an admission with neither a patient nor a prescription
UNKNOWN_ADMISSION = 991503


def _delete_admission(admission):
    """Remove every row this module may have created for an admission."""
    session.execute(
        text("DELETE FROM demo.pessoa_audit WHERE nratendimento = :admission"),
        {"admission": admission},
    )
    session.execute(
        text("DELETE FROM demo.pessoa WHERE nratendimento = :admission"),
        {"admission": admission},
    )


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
    session_commit()

    yield p

    _delete_admission(ADMISSION)
    session.execute(
        text("DELETE FROM demo.prescricao WHERE fkprescricao = :id"),
        {"id": PRESCRIPTION},
    )
    session_commit()


@pytest.fixture
def prescription_without_patient():
    """An admission that has a prescription but no patient row yet."""
    _delete_admission(ORPHAN_ADMISSION)
    session_commit()

    prescription = create_prescription(
        id=ORPHAN_PRESCRIPTION,
        admissionNumber=ORPHAN_ADMISSION,
        idPatient=1,
        idHospital=1,
        date=datetime.now(),
    )

    yield prescription

    _delete_admission(ORPHAN_ADMISSION)
    session.execute(
        text("DELETE FROM demo.prescricao WHERE fkprescricao = :id"),
        {"id": ORPHAN_PRESCRIPTION},
    )
    session_commit()


def _save(client, headers, data, admission=ADMISSION):
    """POST the given payload to the patient endpoint."""
    return client.post(f"/patient/{admission}", json=data, headers=headers)


def _stored(admission=ADMISSION):
    """Read the patient row as it is currently persisted."""
    session.expire_all()
    return session.get(Patient, admission)


def _audits(audit_type, admission=ADMISSION):
    """Read the audit rows of one type recorded for the admission."""
    session.expire_all()
    return (
        session.query(PatientAudit)
        .filter(PatientAudit.admissionNumber == admission)
        .filter(PatientAudit.auditType == audit_type.value)
        .all()
    )


class TestClinicalData:
    """Fields a WRITE_PRESCRIPTION caller may write."""

    def test_save_persists_every_clinical_field(self, client, analyst_headers, patient):
        """All clinical and demographic fields of one payload are stored [200 OK]."""
        response = _save(
            client,
            analyst_headers,
            {
                "weight": 72.5,
                "height": 168.0,
                "dialysis": "v",
                "pregnant": True,
                "lactating": True,
                "skinColor": "1",
                "gender": "F",
                "birthdate": "1980-05-10T00:00:00",
                "observation": "Paciente de teste",
            },
        )

        assert response.status_code == 200

        stored = _stored()
        assert stored.weight == 72.5
        assert stored.height == 168.0
        assert stored.dialysis == "v"
        assert stored.pregnant is True
        assert stored.lactating is True
        assert stored.skinColor == "1"
        assert stored.gender == "F"
        # dtnascimento is a DATE column, so the time part of the payload is dropped
        assert stored.birthdate == date(1980, 5, 10)
        assert stored.observation == "Paciente de teste"

    def test_response_echoes_the_admission_number_as_an_integer(
        self, client, analyst_headers, patient
    ):
        """The response carries the admission number the caller addressed."""
        response = _save(client, analyst_headers, {"height": 170.0})

        assert response.get_json()["data"]["admissionNumber"] == ADMISSION

    def test_fields_left_out_of_the_payload_are_untouched(
        self, client, analyst_headers, patient
    ):
        """Only the keys present in the payload are written."""
        _save(client, analyst_headers, {"weight": 80.0, "height": 175.0})
        _save(client, analyst_headers, {"height": 176.0})

        stored = _stored()
        assert stored.height == 176.0
        assert stored.weight == 80.0

    def test_a_field_can_be_cleared_with_an_explicit_null(
        self, client, analyst_headers, patient
    ):
        """Sending null for a key present in the payload clears the field."""
        _save(client, analyst_headers, {"dialysis": "v"})
        _save(client, analyst_headers, {"dialysis": None})

        assert _stored().dialysis is None

    def test_save_stamps_the_update_metadata(self, client, analyst_headers, patient):
        """Every save records when it happened and who made it."""
        before = datetime.now() - timedelta(seconds=5)

        _save(client, analyst_headers, {"height": 170.0})

        stored = _stored()
        assert stored.update >= before
        assert stored.user is not None


class TestWeight:
    """A changed weight drives the prescription recalculation."""

    def test_new_weight_stamps_the_weight_date(
        self, client, analyst_headers, patient
    ):
        """Storing a weight records the date it was measured."""
        before = datetime.now() - timedelta(seconds=5)

        _save(client, analyst_headers, {"weight": 70.0})

        stored = _stored()
        assert stored.weight == 70.0
        assert stored.weightDate >= before

    def test_changed_weight_asks_for_a_recalculation(
        self, client, analyst_headers, patient
    ):
        """updatePrescription tells the caller the scores are now stale."""
        response = _save(client, analyst_headers, {"weight": 70.0})

        assert response.get_json()["data"]["updatePrescription"] is True

    def test_unchanged_weight_does_not_ask_for_a_recalculation(
        self, client, analyst_headers, patient
    ):
        """Re-sending the same weight is a no-op for the prescription."""
        _save(client, analyst_headers, {"weight": 70.0})
        first_date = _stored().weightDate

        response = _save(client, analyst_headers, {"weight": 70.0})

        assert response.get_json()["data"]["updatePrescription"] is False
        assert _stored().weightDate == first_date

    def test_other_fields_do_not_ask_for_a_recalculation(
        self, client, analyst_headers, patient
    ):
        """Only the weight affects the recalculation flag."""
        response = _save(client, analyst_headers, {"height": 170.0})

        assert response.get_json()["data"]["updatePrescription"] is False


class TestClinicalAlert:
    """The free-text alert is only kept together with an expiry date."""

    def test_alert_is_stored_with_its_expiry_date_and_author(
        self, client, analyst_headers, patient
    ):
        """An alert with an expiry records the text, the dates and the author."""
        expire = (datetime.now() + timedelta(days=7)).replace(microsecond=0)
        before = datetime.now() - timedelta(seconds=5)

        response = _save(
            client,
            analyst_headers,
            {"alert": "Alerta de teste", "alertExpire": expire.isoformat()},
        )

        assert response.status_code == 200

        stored = _stored()
        assert stored.alert == "Alerta de teste"
        assert stored.alertExpire == expire
        assert stored.alertDate >= before
        assert stored.alertBy is not None

    def test_alert_without_an_expiry_date_is_ignored(
        self, client, analyst_headers, patient
    ):
        """An alert with no expiry is never stored."""
        response = _save(client, analyst_headers, {"alert": "Alerta sem vigência"})

        assert response.status_code == 200
        assert _stored().alert is None

    def test_a_later_save_replaces_the_alert_text(
        self, client, analyst_headers, patient
    ):
        """Each save carrying an expiry rewrites the alert.

        The guard that compares the incoming expiry with the stored one reads
        the raw payload, where the date is still an ISO string, so it never
        matches the datetime already on the row. The practical effect is that
        the latest text always wins, which is what this asserts.
        """
        expire = (datetime.now() + timedelta(days=7)).replace(microsecond=0).isoformat()

        _save(client, analyst_headers, {"alert": "Primeiro", "alertExpire": expire})
        _save(client, analyst_headers, {"alert": "Segundo", "alertExpire": expire})

        assert _stored().alert == "Segundo"


class TestAudit:
    """Every save is audited; an observation change is audited twice."""

    def test_every_save_records_an_upsert_audit(
        self, client, analyst_headers, patient
    ):
        """The UPSERT audit snapshots the patient after the save."""
        _save(client, analyst_headers, {"weight": 65.0, "gender": "M"})

        audits = _audits(PatientAuditTypeEnum.UPSERT)

        assert len(audits) == 1
        assert audits[0].extra["weight"] == 65.0
        assert audits[0].extra["gender"] == "M"
        assert audits[0].createdBy is not None

    def test_changed_observation_records_an_observation_audit(
        self, client, analyst_headers, patient
    ):
        """The observation history is fed by its own audit type."""
        _save(client, analyst_headers, {"observation": "Primeira anotação"})

        audits = _audits(PatientAuditTypeEnum.OBSERVATION_RECORD)

        assert len(audits) == 1
        assert audits[0].extra["text"] == "Primeira anotação"

    def test_unchanged_observation_records_no_observation_audit(
        self, client, analyst_headers, patient
    ):
        """Re-sending the same text does not add a history entry."""
        _save(client, analyst_headers, {"observation": "Mesma anotação"})
        _save(client, analyst_headers, {"observation": "Mesma anotação"})

        assert len(_audits(PatientAuditTypeEnum.OBSERVATION_RECORD)) == 1

    def test_save_without_observation_records_no_observation_audit(
        self, client, analyst_headers, patient
    ):
        """A payload that does not carry the key leaves the history alone."""
        _save(client, analyst_headers, {"height": 170.0})

        assert _audits(PatientAuditTypeEnum.OBSERVATION_RECORD) == []


class TestAuthorization:
    """Each group of fields has its own permission."""

    def test_viewer_cannot_save(self, client, viewer_headers, patient):
        """A viewer holds none of the permissions the endpoint accepts [401]."""
        response = _save(client, viewer_headers, {"weight": 70.0})

        assert response.status_code == 401
        assert _stored().weight is None

    def test_analyst_cannot_set_the_discharge_date(
        self, client, analyst_headers, patient
    ):
        """The discharge date needs ADMIN_PATIENT or READ_NAV, which an analyst lacks."""
        response = _save(
            client, analyst_headers, {"dischargeDate": "2026-01-10T00:00:00"}
        )

        assert response.status_code == 200
        assert _stored().dischargeDate is None

    def test_navigator_sets_the_discharge_date(
        self, client, navigator_headers, patient
    ):
        """A navigator holds READ_NAV, so the discharge date is written [200 OK]."""
        response = _save(
            client, navigator_headers, {"dischargeDate": "2026-01-10T00:00:00"}
        )

        assert response.status_code == 200
        assert _stored().dischargeDate == datetime(2026, 1, 10)

    def test_navigator_cannot_write_clinical_data(
        self, client, navigator_headers, patient
    ):
        """A navigator has no WRITE_PRESCRIPTION, so the weight is dropped."""
        response = _save(client, navigator_headers, {"weight": 70.0})

        assert response.status_code == 200
        assert _stored().weight is None

    def test_name_requires_the_write_name_permission(
        self, client, analyst_headers, patient
    ):
        """An analyst cannot rename the patient [401 UNAUTHORIZED]."""
        response = _save(
            client,
            analyst_headers,
            {"height": 170.0, "name": {"name": "Fulano Beltrano"}},
        )

        assert response.status_code == 401
        assert _stored().height is None


class TestImplicitCreation:
    """A patient row is created on demand from the admission's prescriptions."""

    def test_save_creates_the_patient_from_the_first_prescription(
        self, client, analyst_headers, prescription_without_patient
    ):
        """The new row inherits patient, hospital and admission date [200 OK]."""
        response = _save(
            client, analyst_headers, {"weight": 60.0}, admission=ORPHAN_ADMISSION
        )

        assert response.status_code == 200

        stored = _stored(ORPHAN_ADMISSION)
        assert stored is not None
        assert stored.weight == 60.0
        assert stored.idPatient == prescription_without_patient.idPatient
        assert stored.idHospital == prescription_without_patient.idHospital
        assert stored.admissionDate == prescription_without_patient.date

    def test_save_fails_for_an_admission_without_prescriptions(
        self, client, analyst_headers
    ):
        """There is nothing to build the patient from [400 BAD REQUEST]."""
        response = _save(
            client, analyst_headers, {"weight": 60.0}, admission=UNKNOWN_ADMISSION
        )

        assert response.status_code == 400
        assert _stored(UNKNOWN_ADMISSION) is None
