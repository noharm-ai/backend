"""Integration tests for GET /prescriptions/<idPrescription>/update.

The endpoint re-runs the database side of the prescription pipeline for one
prescription. Nothing in the suite covered it, yet it is what a pharmacist
reaches for when a prescription shows stale scores after a drug attribute or a
segment configuration changed.

``prescription_service.recalculate_prescription`` works in two steps:

* it back-fills the patient weight from a recent previous admission, so a
  weight-based score can be computed at all;
* it forces the derived columns to be recomputed. Every item is first marked
  with the ``idoutlier = 99999`` sentinel and the rows are then re-inserted;
  the ``BEFORE INSERT`` triggers on ``prescricao``/``presmed`` intercept the
  insert, recompute segment, outlier and score, and upsert the row in place
  instead of duplicating it.

Which rows are touched depends on the prescription:

* a plain prescription recalculates only itself;
* an aggregated prescription of a non-CPOE segment recalculates every
  prescription of the same admission on the same date;
* an aggregated prescription of a CPOE segment resolves its group first and
  also copies hospital/department/segment onto the prescriptions of the group
  that have no segment yet.

Test data uses the shared ``test_counters`` ranges (prescriptions >= 100000,
items >= 100000001, admissions >= 100000) so ``clean_test_artifacts`` removes
it, including the ``pessoa``/``pessoa_audit`` rows created here.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from models.enums import PatientAuditTypeEnum
from models.prescription import Patient
from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)

# seed segments: 1 is not CPOE, 2 is
_SEGMENT = 1
_CPOE_SEGMENT = 2
_CPOE_DEPARTMENT = 3

# seed drug with outlier rows in segment 1, so the recomputed score is not null
_DRUG = 3

_SEED_PRESCRIPTION = 20


def _next_ids():
    """Reserve a prescription id + admission number no other test uses."""
    id_prescription = test_counters["id_prescription"]
    admission_number = test_counters["admission_number"]
    test_counters["id_prescription"] += 1
    test_counters["admission_number"] += 1

    return id_prescription, admission_number


def _create_patient(admission_number: int, id_patient: int, weight=None, weight_date=None):
    """Insert one admission of a patient."""
    patient = Patient()
    patient.admissionNumber = admission_number
    patient.idPatient = id_patient
    patient.idHospital = 1
    patient.admissionDate = datetime.now()
    patient.birthdate = datetime(1960, 1, 1)
    patient.gender = "M"
    patient.weight = weight
    patient.weightDate = weight_date
    session.add(patient)
    session_commit()

    return patient


def _create_prescription_with_item(
    id_prescription: int,
    admission_number: int,
    id_patient: int = 1,
    id_segment: int = _SEGMENT,
    id_department: int = 1,
    date: datetime = None,
    agg: bool = None,
):
    """Create a prescription holding a single scored item."""
    date = date or datetime.now()

    create_prescription(
        id=id_prescription,
        admissionNumber=admission_number,
        idPatient=id_patient,
        idSegment=id_segment,
        idDepartment=id_department,
        date=date,
        expire=date + timedelta(days=1),
        agg=agg,
    )

    if not agg:
        create_prescription_drug(
            # `<prescription id>001`, so the item id stays above the 100000001
            # cleanup threshold used by tests/conftest.py
            id=int(f"{id_prescription}001"),
            idPrescription=id_prescription,
            idDrug=_DRUG,
            idSegment=id_segment,
        )

    session_commit()

    return id_prescription


def _items(id_prescription: int) -> list[tuple]:
    """Return (id, outlier, score) of every item of a prescription."""
    session_commit()

    return session.execute(
        text(
            "SELECT fkpresmed, idoutlier, escorefinal FROM demo.presmed "
            "WHERE fkprescricao = :id ORDER BY fkpresmed"
        ),
        {"id": id_prescription},
    ).fetchall()


def _break_items(id_prescription: int):
    """Overwrite the derived columns of every item with wrong values."""
    session.execute(
        text(
            "UPDATE demo.presmed SET idoutlier = 1, escorefinal = 0 "
            "WHERE fkprescricao = :id"
        ),
        {"id": id_prescription},
    )
    session_commit()


def _location(id_prescription: int) -> tuple:
    """Return (segment, hospital, department) of a prescription."""
    session_commit()

    return session.execute(
        text(
            "SELECT idsegmento, fkhospital, fksetor FROM demo.prescricao "
            "WHERE fkprescricao = :id"
        ),
        {"id": id_prescription},
    ).first()


def _recalculate(client, headers, id_prescription: int):
    """Call the recalculation endpoint."""
    return client.get(f"/prescriptions/{id_prescription}/update", headers=headers)


class TestSinglePrescription:
    """A prescription that is not an aggregate recalculates only its own items."""

    def test_recalculation_restores_the_derived_columns(self, client, analyst_headers):
        """Outlier and score are recomputed from the current configuration"""
        id_prescription, admission_number = _next_ids()
        _create_prescription_with_item(id_prescription, admission_number)

        expected = _items(id_prescription)
        assert expected, "the item should have been scored on insert"

        _break_items(id_prescription)
        assert _items(id_prescription) != expected

        response = _recalculate(client, analyst_headers, id_prescription)

        assert response.status_code == 200
        assert response.get_json()["data"] == str(id_prescription)
        assert _items(id_prescription) == expected

    def test_recalculation_does_not_duplicate_the_items(self, client, analyst_headers):
        """The re-insert is turned into an upsert by the trigger, not a new row"""
        id_prescription, admission_number = _next_ids()
        _create_prescription_with_item(id_prescription, admission_number)

        before = _items(id_prescription)

        assert _recalculate(client, analyst_headers, id_prescription).status_code == 200

        after = _items(id_prescription)
        assert len(after) == len(before)
        assert [row[0] for row in after] == [row[0] for row in before]

    def test_unknown_prescription_is_rejected(self, client, analyst_headers):
        """A prescription that does not exist answers 400 instead of doing nothing"""
        response = _recalculate(client, analyst_headers, 987654321)

        assert response.status_code == 400
        assert response.get_json()["code"] == "errors.invalidRegister"

    def test_reading_a_prescription_is_not_enough(self, client, viewer_headers):
        """A viewer cannot trigger a recalculation"""
        response = _recalculate(client, viewer_headers, _SEED_PRESCRIPTION)

        assert response.status_code == 401

    def test_drug_score_permission_is_accepted(self, client, config_manager_headers):
        """WRITE_DRUG_SCORE alone opens the endpoint, WRITE_PRESCRIPTION is not required"""
        response = _recalculate(client, config_manager_headers, _SEED_PRESCRIPTION)

        assert response.status_code == 200


class TestAggregatedPrescription:
    """An aggregate stands for every prescription of the admission on its date."""

    def test_aggregate_recalculates_the_prescriptions_of_its_date(
        self, client, analyst_headers
    ):
        """Items of a prescription covered by the aggregate are recomputed"""
        id_aggregate, admission_number = _next_ids()
        id_prescription, _ = _next_ids()
        date = datetime.now()

        _create_prescription_with_item(
            id_aggregate, admission_number, date=date, agg=True
        )
        _create_prescription_with_item(id_prescription, admission_number, date=date)

        expected = _items(id_prescription)
        _break_items(id_prescription)

        assert _recalculate(client, analyst_headers, id_aggregate).status_code == 200

        assert _items(id_prescription) == expected

    def test_aggregate_leaves_another_date_alone(self, client, analyst_headers):
        """A prescription outside the aggregate date keeps its values untouched"""
        id_aggregate, admission_number = _next_ids()
        id_other, _ = _next_ids()

        _create_prescription_with_item(
            id_aggregate, admission_number, date=datetime.now(), agg=True
        )
        _create_prescription_with_item(
            id_other, admission_number, date=datetime.now() - timedelta(days=10)
        )

        _break_items(id_other)
        broken = _items(id_other)

        assert _recalculate(client, analyst_headers, id_aggregate).status_code == 200

        assert _items(id_other) == broken

    def test_cpoe_aggregate_fills_the_location_of_its_group(
        self, client, analyst_headers
    ):
        """In CPOE the aggregate hands hospital, department and segment down"""
        id_aggregate, admission_number = _next_ids()
        id_prescription, _ = _next_ids()
        date = datetime.now()

        _create_prescription_with_item(
            id_aggregate,
            admission_number,
            id_segment=_CPOE_SEGMENT,
            id_department=_CPOE_DEPARTMENT,
            date=date,
            agg=True,
        )
        _create_prescription_with_item(
            id_prescription,
            admission_number,
            id_segment=_CPOE_SEGMENT,
            id_department=_CPOE_DEPARTMENT,
            date=date,
        )

        # a prescription the integration delivered before its segment was known
        session.execute(
            text("UPDATE demo.prescricao SET idsegmento = NULL WHERE fkprescricao = :id"),
            {"id": id_prescription},
        )
        session_commit()
        assert _location(id_prescription)[0] is None

        assert _recalculate(client, analyst_headers, id_aggregate).status_code == 200

        assert _location(id_prescription) == _location(id_aggregate)


class TestPatientWeight:
    """The weight of the admission is back-filled from a previous admission."""

    def _admission_without_weight(self, previous_weight=None, previous_weight_date=None):
        """Create an admission with no weight, optionally preceded by one that has it."""
        id_prescription, admission_number = _next_ids()
        _, previous_admission = _next_ids()
        id_patient = admission_number

        if previous_weight is not None:
            _create_patient(
                previous_admission,
                id_patient,
                weight=previous_weight,
                weight_date=previous_weight_date,
            )

        _create_patient(admission_number, id_patient)
        _create_prescription_with_item(id_prescription, admission_number, id_patient)

        return id_prescription, admission_number

    def _weight(self, admission_number: int):
        """Return the stored weight of an admission."""
        session_commit()

        return session.execute(
            text("SELECT peso FROM demo.pessoa WHERE nratendimento = :admission"),
            {"admission": admission_number},
        ).scalar()

    def _audits(self, admission_number: int) -> list[tuple]:
        """Return the audit rows written for an admission."""
        session_commit()

        return session.execute(
            text(
                "SELECT tp_audit, extra FROM demo.pessoa_audit "
                "WHERE nratendimento = :admission"
            ),
            {"admission": admission_number},
        ).fetchall()

    def test_weight_is_copied_from_a_recent_admission(self, client, analyst_headers):
        """A weight measured in the last month is carried over and audited"""
        id_prescription, admission_number = self._admission_without_weight(
            previous_weight=82.5,
            previous_weight_date=datetime.now() - timedelta(days=3),
        )

        assert _recalculate(client, analyst_headers, id_prescription).status_code == 200

        assert self._weight(admission_number) == pytest.approx(82.5)

        audits = self._audits(admission_number)
        assert len(audits) == 1
        audit_type, extra = audits[0]
        assert audit_type == PatientAuditTypeEnum.UPSERT.value
        assert extra["weight"] == pytest.approx(82.5)
        assert extra["source"] == "recalculate_prescription"

    def test_a_weight_older_than_a_month_is_not_used(self, client, analyst_headers):
        """An outdated measurement is not carried over"""
        id_prescription, admission_number = self._admission_without_weight(
            previous_weight=70.0,
            previous_weight_date=datetime.now() - timedelta(days=60),
        )

        assert _recalculate(client, analyst_headers, id_prescription).status_code == 200

        assert self._weight(admission_number) is None
        assert self._audits(admission_number) == []

    def test_nothing_is_written_when_there_is_no_previous_admission(
        self, client, analyst_headers
    ):
        """A patient seen for the first time keeps an empty weight"""
        id_prescription, admission_number = self._admission_without_weight()

        assert _recalculate(client, analyst_headers, id_prescription).status_code == 200

        assert self._weight(admission_number) is None
        assert self._audits(admission_number) == []

    def test_an_existing_weight_is_kept(self, client, analyst_headers):
        """The weight already recorded for the admission wins over the previous one"""
        id_prescription, admission_number = _next_ids()
        _, previous_admission = _next_ids()
        id_patient = admission_number

        _create_patient(
            previous_admission,
            id_patient,
            weight=82.5,
            weight_date=datetime.now() - timedelta(days=3),
        )
        _create_patient(
            admission_number,
            id_patient,
            weight=64.0,
            weight_date=datetime.now() - timedelta(days=1),
        )
        _create_prescription_with_item(id_prescription, admission_number, id_patient)

        assert _recalculate(client, analyst_headers, id_prescription).status_code == 200

        assert self._weight(admission_number) == pytest.approx(64.0)
        assert self._audits(admission_number) == []
