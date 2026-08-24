"""Tests: prescription drug check history (GET /prescriptions/drug/<id>/check-history).

Covers ``prescription_drug_service.get_drug_check_history``, which reports, for a
single presmed row:

* ``audit``  — the latest ``presmed_audit`` UPSERT record, written by the database
  ingestion trigger when the drug is created/updated by the integration;
* ``current`` — the drug's values right now;
* ``records`` — the ``checkedindex`` snapshots taken every time a prescription of
  the same admission holding the same drug was checked, each flagged with the
  fields that diverged from ``current``.

Note on ``records``: a check writes a snapshot twice — once by the database
trigger on ``prescricao`` (no author, no prescription id) and once by
``prescription_check_service._add_checkedindex`` (with both). Assertions below
that care about provenance look at the authored rows, which is what carries the
"who checked it" information the endpoint exposes.
"""

from datetime import datetime

from sqlalchemy import text

from models.enums import PrescriptionDrugAuditTypeEnum
from models.prescription import PrescriptionDrug
from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)

CHECK_URL = "/prescriptions/status"
DEMO_USER_NAME = "Demonstração"


def _history_url(id_prescription_drug):
    return f"/prescriptions/drug/{id_prescription_drug}/check-history"


def _next_ids():
    """Reserve a unique prescription id and admission number for a test."""
    id_prescription = test_counters["id_prescription"]
    admission_number = test_counters["admission_number"]
    test_counters["id_prescription"] += 1
    test_counters["admission_number"] += 1
    return id_prescription, admission_number


def _create_prescription_with_drug(admission_number=None, id_drug=3, dose=100.0):
    """Create a prescription holding a single drug and return (prescription, presmed id).

    The presmed id ends in ``500`` so it never collides with getNextId, which
    mints new ids as ``concat(prescription_id, lpad(count, 3))``.
    """
    id_prescription, next_admission = _next_ids()
    if admission_number is None:
        admission_number = next_admission

    prescription = create_prescription(
        id=id_prescription, admissionNumber=admission_number, idPatient=1
    )
    id_prescription_drug = int(f"{id_prescription}500")
    create_prescription_drug(
        id=id_prescription_drug,
        idPrescription=id_prescription,
        idDrug=id_drug,
        dose=dose,
    )

    return prescription, id_prescription_drug


def _check(client, headers, id_prescription):
    """Check a prescription, which snapshots its active drugs into checkedindex."""
    return client.post(
        CHECK_URL,
        json={
            "idPrescription": id_prescription,
            "status": "s",
            "evaluationTime": 0,
            "alerts": [],
            "fastCheck": False,
        },
        headers=headers,
    )


def _get_history(client, headers, id_prescription_drug):
    """Read the check history payload for a presmed row."""
    response = client.get(_history_url(id_prescription_drug), headers=headers)
    assert response.status_code == 200

    return response.get_json()["data"]


def _authored(records):
    """Keep the snapshots written by the application (the ones carrying an author)."""
    return [r for r in records if r["createdBy"] is not None]


def _add_insertion_audit(id_prescription_drug, extra):
    """Insert a presmed_audit UPSERT row newer than every other one for this drug."""
    session.execute(
        text(
            "INSERT INTO demo.presmed_audit "
            "(tp_audit, fkpresmed, extra, created_at, created_by) "
            "SELECT :kind, :id, CAST(:extra AS json), "
            "COALESCE(MAX(created_at), now()) + interval '1 second', 1 "
            "FROM demo.presmed_audit WHERE fkpresmed = :id"
        ),
        {
            "kind": PrescriptionDrugAuditTypeEnum.UPSERT.value,
            "id": id_prescription_drug,
            "extra": extra,
        },
    )
    session_commit()


def test_check_history_requires_read_prescription(client, user_manager_headers):
    """A user without READ_PRESCRIPTION cannot read the check history [401 UNAUTHORIZED]."""
    _, id_prescription_drug = _create_prescription_with_drug()

    response = client.get(
        _history_url(id_prescription_drug), headers=user_manager_headers
    )

    assert response.status_code == 401


def test_check_history_unknown_prescription_drug(client, analyst_headers):
    """An unknown presmed id returns a validation error [400 BAD REQUEST]."""
    response = client.get(_history_url(100999999), headers=analyst_headers)

    assert response.status_code == 400


def test_check_history_empty_before_any_check(client, analyst_headers):
    """A drug that was never checked has no snapshots, only its current values."""
    _, id_prescription_drug = _create_prescription_with_drug(dose=100.0)

    data = _get_history(client, analyst_headers, id_prescription_drug)

    assert data["records"] == []
    assert data["current"] == {
        "dose": 100.0,
        "doseconv": 100.0,
        "frequencyDay": 1.0,
        "route": "VO",
        "interval": None,
    }


def test_check_history_exposes_the_ingestion_audit(client, analyst_headers):
    """The audit block carries the UPSERT record written when the drug was ingested."""
    _, id_prescription_drug = _create_prescription_with_drug()

    audit = _get_history(client, analyst_headers, id_prescription_drug)["audit"]

    assert audit["createdAt"] is not None
    assert audit["config"]["origem_pep"] == "Medicamentos"
    assert audit["config"]["idsegmento"] == 1


def test_check_history_returns_latest_insertion_audit(client, analyst_headers):
    """When the drug is re-ingested, the newest UPSERT audit is the one reported."""
    _, id_prescription_drug = _create_prescription_with_drug()

    _add_insertion_audit(id_prescription_drug, '{"origem_pep": "Soluções"}')

    audit = _get_history(client, analyst_headers, id_prescription_drug)["audit"]

    assert audit["config"] == {"origem_pep": "Soluções"}


def test_check_history_snapshots_the_drug_on_check(client, analyst_headers):
    """Checking a prescription records a snapshot that matches the current values."""
    prescription, id_prescription_drug = _create_prescription_with_drug()

    assert _check(client, analyst_headers, prescription.id).status_code == 200

    records = _authored(
        _get_history(client, analyst_headers, id_prescription_drug)["records"]
    )
    assert len(records) == 1

    record = records[0]
    assert record["idPrescription"] == str(prescription.id)
    assert record["dose"] == 100.0
    assert record["doseconv"] == 100.0
    assert record["frequencyDay"] == 1.0
    assert record["route"] == "VO"
    assert record["interval"] == ""
    assert record["createdBy"] == DEMO_USER_NAME
    assert record["createdAt"] is not None
    assert record["prescriptionDate"] is not None

    # nothing changed since the check, so the snapshot is a full match
    assert record["match"] is True
    assert record["matchDiff"] == []


def test_check_history_flags_fields_that_changed_since_the_check(
    client, analyst_headers
):
    """A snapshot taken before an edit reports exactly the fields that diverged."""
    prescription, id_prescription_drug = _create_prescription_with_drug(dose=100.0)

    assert _check(client, analyst_headers, prescription.id).status_code == 200

    drug = (
        session.query(PrescriptionDrug)
        .filter(PrescriptionDrug.id == id_prescription_drug)
        .first()
    )
    drug.dose = 250.0
    drug.doseconv = 250.0
    drug.route = "IV"
    session_commit()

    data = _get_history(client, analyst_headers, id_prescription_drug)
    assert data["current"]["dose"] == 250.0
    assert data["current"]["route"] == "IV"

    for record in data["records"]:
        assert record["match"] is False
        assert sorted(record["matchDiff"]) == ["dose", "doseconv", "via"]

        # the snapshot keeps the values as they were at check time
        assert record["dose"] == 100.0
        assert record["route"] == "VO"


def test_check_history_spans_the_admission_newest_first(client, analyst_headers):
    """Snapshots of the same drug on other prescriptions of the admission are included."""
    first, first_drug_id = _create_prescription_with_drug(id_drug=3)
    second, _ = _create_prescription_with_drug(
        admission_number=first.admissionNumber, id_drug=3
    )

    assert _check(client, analyst_headers, first.id).status_code == 200
    assert _check(client, analyst_headers, second.id).status_code == 200

    records = _get_history(client, analyst_headers, first_drug_id)["records"]

    # ordered by check time, newest first
    assert [r["createdAt"] for r in records] == sorted(
        [r["createdAt"] for r in records], reverse=True
    )
    assert [r["idPrescription"] for r in _authored(records)] == [
        str(second.id),
        str(first.id),
    ]


def test_check_history_ignores_other_drugs_of_the_admission(client, analyst_headers):
    """Only snapshots of the requested drug are returned, not the whole admission."""
    prescription, id_prescription_drug = _create_prescription_with_drug(
        id_drug=3, dose=100.0
    )
    other_drug_id = int(f"{prescription.id}501")
    create_prescription_drug(
        id=other_drug_id, idPrescription=prescription.id, idDrug=4, dose=777.0
    )

    assert _check(client, analyst_headers, prescription.id).status_code == 200

    records = _get_history(client, analyst_headers, id_prescription_drug)["records"]
    assert records
    assert all(r["dose"] == 100.0 for r in records)

    other_records = _get_history(client, analyst_headers, other_drug_id)["records"]
    assert other_records
    assert all(r["dose"] == 777.0 for r in other_records)


def test_check_history_ignores_suspended_drugs(client, analyst_headers):
    """A suspended drug is not snapshotted when the prescription is checked."""
    prescription, id_prescription_drug = _create_prescription_with_drug()

    drug = (
        session.query(PrescriptionDrug)
        .filter(PrescriptionDrug.id == id_prescription_drug)
        .first()
    )
    drug.suspendedDate = datetime.now()
    session_commit()

    assert _check(client, analyst_headers, prescription.id).status_code == 200

    assert _get_history(client, analyst_headers, id_prescription_drug)["records"] == []
