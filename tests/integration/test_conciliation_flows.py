"""Tests: medication conciliation flows (services.conciliation_service).

Covers the three /conciliation endpoints, none of which had coverage before:

* ``POST /conciliation/create`` — opens the daily conciliation prescription for
  an admission (one per admission per day) and flips the patient conciliation
  status from PENDING to CREATED.
* ``GET /conciliation/list-available`` — lists the five most recent
  conciliations of an admission.
* ``POST /conciliation/copy`` — refills a conciliation with the items of the
  patient's previous conciliation, skipping suspended items.

All three are gated by schema features (``CONCILIATION`` /
``CONCILIATION_EDIT``). Features are resolved from the JWT claims first and
then from the schema ``features`` memory, so the tests toggle the memory row
(the claims are frozen at authentication time).
"""

import json
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import text

from models.enums import PatientConciliationStatusEnum
from models.prescription import Patient, Prescription, PrescriptionDrug
from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import (
    create_basic_prescription,
    create_prescription,
    create_prescription_drug,
    test_counters,
)
from utils import prescriptionutils

CONCILIATION = "CONCILIATION"
CONCILIATION_EDIT = "CONCILIATION_EDIT"

# presmed ids for hand-built conciliation items. Above the cleanup threshold
# (100000001) used by tests/conftest.py and far from the `<prescription id>NNN`
# ids minted by utils_test_prescription, which stay below 10^9.
_item_id = {"next": 10**12}


def _next_item_id():
    """Reserve a unique presmed id for a hand-built conciliation item."""
    _item_id["next"] += 1
    return _item_id["next"]


def _next_admission():
    """Reserve an admission number not used by any other test."""
    admission = test_counters["admission_number"]
    test_counters["admission_number"] += 1
    return admission


def _read_features():
    """Return the feature list currently stored in the demo schema."""
    row = session.execute(
        text("SELECT valor FROM demo.memoria WHERE tipo = 'features'")
    ).first()
    return list(row[0]) if row else []


def _write_features(features):
    """Overwrite the demo schema feature list."""
    session.execute(
        text(
            "UPDATE demo.memoria SET valor = CAST(:value AS json) WHERE tipo = 'features'"
        ),
        {"value": json.dumps(features)},
    )
    session_commit()


@pytest.fixture
def conciliation_features():
    """Enable both conciliation features for the demo schema."""
    original = _read_features()
    _write_features(original + [CONCILIATION, CONCILIATION_EDIT])
    yield
    _write_features(original)


def _conciliation_id(admission_number, pdate, id_segment=1):
    """Reproduce the id conciliation_service mints for a given day."""
    return 90000000000000000 + prescriptionutils.gen_agg_id(
        admission_number=admission_number, id_segment=id_segment, pdate=pdate
    )


def _create_conciliation_prescription(admission_number, pdate, id_patient, status=None):
    """Insert a conciliation prescription (concilia = 's') directly.

    The ``complete_prescricao`` insert trigger does not carry ``status``, so a
    non-default status is applied with a follow-up update.
    """
    prescription = create_prescription(
        id=_conciliation_id(admission_number=admission_number, pdate=pdate),
        admissionNumber=admission_number,
        idPatient=id_patient,
        date=pdate,
        expire=pdate,
        concilia="s",
    )

    if status is not None:
        session.execute(
            text(
                "UPDATE demo.prescricao SET status = :status WHERE fkprescricao = :id"
            ),
            {"status": status, "id": prescription.id},
        )
        session_commit()

    return prescription


def _create(client, headers, admission_number):
    return client.post(
        "/conciliation/create",
        json={"admissionNumber": admission_number},
        headers=headers,
    )


def _list_available(client, headers, admission_number):
    return client.get(
        f"/conciliation/list-available?admissionNumber={admission_number}",
        headers=headers,
    )


def _copy(client, headers, id_prescription):
    return client.post(
        "/conciliation/copy",
        json={"idPrescription": id_prescription},
        headers=headers,
    )


# ---------------------------------------------------------------------------
# POST /conciliation/create
# ---------------------------------------------------------------------------


def test_create_is_blocked_when_feature_is_disabled(client, analyst_headers):
    """POST /conciliation/create answers 401 while CONCILIATION_EDIT is off."""
    prescription = create_basic_prescription()

    response = _create(client, analyst_headers, prescription.admissionNumber)

    assert response.status_code == 401
    assert response.get_json()["code"] == "errors.unauthorizedFeature"


def test_create_rejects_an_admission_without_prescriptions(
    client, analyst_headers, conciliation_features
):
    """An admission with no regular prescription cannot be conciliated."""
    response = _create(client, analyst_headers, _next_admission())

    assert response.status_code == 400
    body = response.get_json()
    assert body["code"] == "errors.businessRules"
    assert "Atendimento inválido" in body["message"]


def test_create_opens_todays_conciliation(
    client, analyst_headers, conciliation_features
):
    """The new prescription reuses the reference's admission data and is flagged."""
    reference = create_basic_prescription()
    session.expire_all()
    reference = session.get(Prescription, reference.id)
    expected_id = _conciliation_id(
        admission_number=reference.admissionNumber,
        pdate=date.today(),
        id_segment=reference.idSegment,
    )

    response = _create(client, analyst_headers, reference.admissionNumber)

    assert response.status_code == 200
    assert response.get_json()["data"] == str(expected_id)

    session.expire_all()
    created = session.get(Prescription, expected_id)
    assert created is not None
    assert created.concilia == "s"
    assert created.agg is None
    assert created.admissionNumber == reference.admissionNumber
    assert created.idPatient == reference.idPatient
    assert created.idDepartment == reference.idDepartment
    assert created.date.date() == date.today()


def test_create_allows_only_one_conciliation_per_day(
    client, analyst_headers, conciliation_features
):
    """A second call on the same day is refused instead of overwriting."""
    reference = create_basic_prescription()

    first = _create(client, analyst_headers, reference.admissionNumber)
    assert first.status_code == 200

    second = _create(client, analyst_headers, reference.admissionNumber)

    assert second.status_code == 400
    body = second.get_json()
    assert body["code"] == "errors.businessRules"
    assert "Somente uma conciliação por dia" in body["message"]


def test_create_moves_the_patient_to_the_created_status(
    client, analyst_headers, conciliation_features
):
    """A patient waiting for conciliation is marked as CREATED."""
    reference = create_basic_prescription()

    patient = Patient()
    patient.admissionNumber = reference.admissionNumber
    patient.idPatient = reference.idPatient
    patient.idHospital = 1
    patient.admissionDate = datetime.now()
    patient.st_conciliation = PatientConciliationStatusEnum.PENDING.value
    session.add(patient)
    session_commit()

    response = _create(client, analyst_headers, reference.admissionNumber)

    assert response.status_code == 200

    session.expire_all()
    updated = session.get(Patient, reference.admissionNumber)
    assert updated.st_conciliation == PatientConciliationStatusEnum.CREATED.value


def test_create_keeps_a_patient_status_that_is_not_pending(
    client, analyst_headers, conciliation_features
):
    """Only the PENDING status is advanced; anything else is left untouched."""
    reference = create_basic_prescription()

    patient = Patient()
    patient.admissionNumber = reference.admissionNumber
    patient.idPatient = reference.idPatient
    patient.idHospital = 1
    patient.admissionDate = datetime.now()
    patient.st_conciliation = PatientConciliationStatusEnum.CREATED.value
    session.add(patient)
    session_commit()

    assert (
        _create(client, analyst_headers, reference.admissionNumber).status_code == 200
    )

    session.expire_all()
    updated = session.get(Patient, reference.admissionNumber)
    assert updated.st_conciliation == PatientConciliationStatusEnum.CREATED.value


# ---------------------------------------------------------------------------
# GET /conciliation/list-available
# ---------------------------------------------------------------------------


def test_list_available_is_blocked_when_feature_is_disabled(client, analyst_headers):
    """The listing is gated by CONCILIATION, not by CONCILIATION_EDIT."""
    response = _list_available(client, analyst_headers, _next_admission())

    assert response.status_code == 401
    assert response.get_json()["code"] == "errors.unauthorizedFeature"


def test_list_available_returns_conciliations_newest_first(
    client, analyst_headers, conciliation_features
):
    """Conciliations come back ordered by date descending, ids as strings."""
    admission = _next_admission()
    id_patient = 990001

    older = _create_conciliation_prescription(
        admission_number=admission,
        pdate=datetime.now() - timedelta(days=3),
        id_patient=id_patient,
    )
    newer = _create_conciliation_prescription(
        admission_number=admission,
        pdate=datetime.now() - timedelta(days=1),
        id_patient=id_patient,
        status="s",
    )

    response = _list_available(client, analyst_headers, admission)

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert [item["id"] for item in data] == [str(newer.id), str(older.id)]
    assert data[0]["status"] == "s"
    assert data[0]["date"] == newer.date.isoformat()


def test_list_available_ignores_regular_prescriptions(
    client, analyst_headers, conciliation_features
):
    """Prescriptions without the concilia flag are not listed."""
    admission = _next_admission()
    id_patient = 990002

    create_prescription(
        id=test_counters["id_prescription"],
        admissionNumber=admission,
        idPatient=id_patient,
    )
    test_counters["id_prescription"] += 1
    conciliation = _create_conciliation_prescription(
        admission_number=admission,
        pdate=datetime.now() - timedelta(days=1),
        id_patient=id_patient,
    )

    response = _list_available(client, analyst_headers, admission)

    data = response.get_json()["data"]
    assert [item["id"] for item in data] == [str(conciliation.id)]


def test_list_available_is_capped_at_five_records(
    client, analyst_headers, conciliation_features
):
    """Older conciliations beyond the fifth are dropped."""
    admission = _next_admission()
    id_patient = 990003

    created = [
        _create_conciliation_prescription(
            admission_number=admission,
            pdate=datetime.now() - timedelta(days=offset),
            id_patient=id_patient,
        )
        for offset in range(1, 8)
    ]

    response = _list_available(client, analyst_headers, admission)

    data = response.get_json()["data"]
    assert len(data) == 5
    # the five most recent ones, i.e. the smallest day offsets
    assert [item["id"] for item in data] == [str(p.id) for p in created[:5]]


# ---------------------------------------------------------------------------
# POST /conciliation/copy
# ---------------------------------------------------------------------------


def test_copy_is_blocked_when_feature_is_disabled(client, analyst_headers):
    """POST /conciliation/copy answers 401 while CONCILIATION_EDIT is off."""
    admission = _next_admission()
    conciliation = _create_conciliation_prescription(
        admission_number=admission,
        pdate=datetime.now(),
        id_patient=990004,
    )

    response = _copy(client, analyst_headers, conciliation.id)

    assert response.status_code == 401
    assert response.get_json()["code"] == "errors.unauthorizedFeature"


def test_copy_rejects_an_unknown_prescription(
    client, analyst_headers, conciliation_features
):
    """A prescription id that does not exist is reported as invalid."""
    response = _copy(client, analyst_headers, 90000000000000001)

    assert response.status_code == 400
    body = response.get_json()
    assert body["code"] == "errors.invalidRecord"
    assert "Conciliação inexistente" in body["message"]


def test_copy_rejects_a_regular_prescription(
    client, analyst_headers, conciliation_features
):
    """Only prescriptions flagged as conciliation can be refilled."""
    prescription = create_basic_prescription()

    response = _copy(client, analyst_headers, prescription.id)

    assert response.status_code == 400
    body = response.get_json()
    assert body["code"] == "errors.businessRules"
    assert "Conciliação inválida" in body["message"]


def test_copy_requires_a_previous_conciliation(
    client, analyst_headers, conciliation_features
):
    """The first conciliation of a patient has nothing to copy from."""
    admission = _next_admission()
    conciliation = _create_conciliation_prescription(
        admission_number=admission,
        pdate=datetime.now(),
        id_patient=990005,
    )

    response = _copy(client, analyst_headers, conciliation.id)

    assert response.status_code == 400
    body = response.get_json()
    assert body["code"] == "errors.businessRules"
    assert "Não foi encontrada conciliação anterior" in body["message"]


def test_copy_duplicates_the_previous_items_and_skips_suspended_ones(
    client, analyst_headers, conciliation_features
):
    """Active items are recreated on the new conciliation; suspended ones are not."""
    admission = _next_admission()
    id_patient = 990006

    previous = _create_conciliation_prescription(
        admission_number=admission,
        pdate=datetime.now() - timedelta(days=2),
        id_patient=id_patient,
    )
    create_prescription_drug(
        id=_next_item_id(),
        idPrescription=previous.id,
        idDrug=3,
        idMeasureUnit="1",
        idFrequency="1",
        dose=42.0,
        route="VO",
        interval="8h",
        notes="manter em jejum",
        source="Medicamentos",
    )
    create_prescription_drug(
        id=_next_item_id(),
        idPrescription=previous.id,
        idDrug=4,
        suspendedDate=datetime.now() - timedelta(days=1),
    )

    current = _create_conciliation_prescription(
        admission_number=admission,
        pdate=datetime.now(),
        id_patient=id_patient,
    )

    response = _copy(client, analyst_headers, current.id)

    assert response.status_code == 200

    session.expire_all()
    copied = (
        session.query(PrescriptionDrug)
        .filter(PrescriptionDrug.idPrescription == current.id)
        .all()
    )

    assert len(copied) == 1
    item = copied[0]
    assert item.idDrug == 3
    assert item.dose == 42.0
    assert item.idMeasureUnit == "1"
    assert item.idFrequency == "1"
    assert item.interval == "8h"
    assert item.route == "VO"
    assert item.notes == "manter em jejum"
    assert item.source == "Medicamentos"


def test_copy_reaches_conciliations_of_a_previous_admission(
    client, analyst_headers, conciliation_features
):
    """The source conciliation may belong to an earlier stay of the same patient."""
    previous_admission = _next_admission()
    current_admission = _next_admission()
    id_patient = 990007

    for admission in (previous_admission, current_admission):
        patient = Patient()
        patient.admissionNumber = admission
        patient.idPatient = id_patient
        patient.idHospital = 1
        patient.admissionDate = datetime.now() - timedelta(days=30)
        session.add(patient)
    session_commit()

    previous = _create_conciliation_prescription(
        admission_number=previous_admission,
        pdate=datetime.now() - timedelta(days=20),
        id_patient=id_patient,
    )
    create_prescription_drug(
        id=_next_item_id(),
        idPrescription=previous.id,
        idDrug=3,
        dose=15.0,
    )

    current = _create_conciliation_prescription(
        admission_number=current_admission,
        pdate=datetime.now(),
        id_patient=id_patient,
    )

    response = _copy(client, analyst_headers, current.id)

    assert response.status_code == 200

    session.expire_all()
    copied = (
        session.query(PrescriptionDrug)
        .filter(PrescriptionDrug.idPrescription == current.id)
        .all()
    )

    assert [(item.idDrug, item.dose) for item in copied] == [(3, 15.0)]
