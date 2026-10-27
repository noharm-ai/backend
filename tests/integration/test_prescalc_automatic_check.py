"""Tests: prescalc automatic check (AUTOMATIC_CHECK_DIET_ONLY, AUTOMATIC_CHECK_WHITELIST_ONLY)

With the features on, prescalc checks an individual prescription that has
nothing to validate (only diets, or only white list drugs) and keeps the
patient-day status: a checked patient-day is not made pending again.
"""

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from models.enums import DrugTypeEnum, FeatureEnum
from models.prescription import Prescription
from static import prescalc
from tests.conftest import session, session_commit
from tests.utils import utils_test_prescription

DIET_ONLY = FeatureEnum.AUTOMATIC_CHECK_DIET_ONLY.value
WHITELIST_ONLY = FeatureEnum.AUTOMATIC_CHECK_WHITELIST_ONLY.value

# seed drug with attributes on segment 1: marked as white list by the fixture
WHITELIST_DRUG = 4
# seed drug with no attributes: never white list
REGULAR_DRUG = 3


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
def features():
    """Set the automatic check features for a test, restoring the original list."""
    original = _read_features()
    clean = [f for f in original if f not in (DIET_ONLY, WHITELIST_ONLY)]

    def _set(*enabled):
        _write_features(clean + list(enabled))

    _set()
    yield _set
    _write_features(original)


@pytest.fixture
def whitelist_drug():
    """Mark WHITELIST_DRUG as white list on segment 1, restoring it afterwards."""
    params = {"id_drug": WHITELIST_DRUG}
    original = session.execute(
        text(
            "SELECT linhabranca FROM demo.medatributos "
            "WHERE fkmedicamento = :id_drug AND idsegmento = 1"
        ),
        params,
    ).scalar()
    session.execute(
        text(
            "UPDATE demo.medatributos SET linhabranca = true "
            "WHERE fkmedicamento = :id_drug AND idsegmento = 1"
        ),
        params,
    )
    session_commit()
    yield
    session.execute(
        text(
            "UPDATE demo.medatributos SET linhabranca = :value "
            "WHERE fkmedicamento = :id_drug AND idsegmento = 1"
        ),
        {**params, "value": original},
    )
    session_commit()


def _create_prescription(items: list[tuple[int, str]], admission_number=None):
    """Create a prescription with the given (idDrug, source) items."""
    counters = utils_test_prescription.test_counters
    id_prescription = counters["id_prescription"]

    prescription = utils_test_prescription.create_prescription(
        id=id_prescription,
        admissionNumber=(
            admission_number
            if admission_number is not None
            else counters["admission_number"]
        ),
        idPatient=1,
        date=datetime.now(),
        expire=datetime.now() + timedelta(days=1),
    )

    for index, (id_drug, source) in enumerate(items, start=1):
        id_prescription_drug = int(f"{id_prescription}{index:03d}")
        utils_test_prescription.create_prescription_drug(
            id=id_prescription_drug,
            idPrescription=id_prescription,
            idDrug=id_drug,
            source=source,
        )

        if source == DrugTypeEnum.MATERIAL.value:
            # the seed has no origin map for materials: the insert trigger
            # stores them as drugs
            session.execute(
                text("UPDATE demo.presmed SET origem = :source WHERE fkpresmed = :id"),
                {"source": source, "id": id_prescription_drug},
            )
            session_commit()

    counters["id_prescription"] += 1
    counters["admission_number"] += 1

    return prescription


def _run_prescalc(id_prescription: int):
    """Run prescalc for a prescription and commit."""
    prescalc(
        {"schema": "demo", "id_prescription": id_prescription, "force": False}, None
    )
    session_commit()


def _status(id_prescription: int):
    """Current status of a prescription."""
    session.expire_all()
    return (
        session.query(Prescription.status)
        .filter(Prescription.id == id_prescription)
        .scalar()
    )


def _patient_day(admission_number: int) -> Prescription:
    """Patient-day prescription of an admission."""
    session.expire_all()
    return (
        session.query(Prescription)
        .filter(Prescription.agg)
        .filter(Prescription.admissionNumber == admission_number)
        .first()
    )


def _checked_patient_day(client, headers, admission_number: int) -> Prescription:
    """Create an admission with a regular prescription and check its patient-day."""
    prescription = _create_prescription(
        [(REGULAR_DRUG, DrugTypeEnum.DRUG.value)], admission_number=admission_number
    )
    _run_prescalc(prescription.id)

    patient_day = _patient_day(admission_number)
    response = client.post(
        "/prescriptions/status",
        json={"status": "s", "idPrescription": patient_day.id},
        headers=headers,
    )
    assert response.status_code == 200
    session_commit()

    assert _status(patient_day.id) == "s"
    return patient_day


def _next_admission_number():
    """Reserve an admission number for a test."""
    counters = utils_test_prescription.test_counters
    admission_number = counters["admission_number"]
    counters["admission_number"] += 1
    return admission_number


# ─── diet only ────────────────────────────────────────────────────────────────


def test_diet_only_feature_off_keeps_pending(features):
    """Without the feature a diet only prescription is not checked."""
    prescription = _create_prescription([(REGULAR_DRUG, DrugTypeEnum.DIET.value)])

    _run_prescalc(prescription.id)

    assert _status(prescription.id) == "0"
    assert _patient_day(prescription.admissionNumber).status == "0"


def test_diet_only_checks_prescription_and_new_patient_day(features):
    """A diet only prescription is checked, and so is its new patient-day."""
    features(DIET_ONLY)
    prescription = _create_prescription(
        [
            (REGULAR_DRUG, DrugTypeEnum.DIET.value),
            (WHITELIST_DRUG, DrugTypeEnum.MATERIAL.value),
        ]
    )

    _run_prescalc(prescription.id)

    assert _status(prescription.id) == "s"
    assert _patient_day(prescription.admissionNumber).status == "s"


def test_diet_only_ignores_prescription_with_drugs(features, whitelist_drug):
    """With only the diet feature, a white list drug is not checked."""
    features(DIET_ONLY)
    prescription = _create_prescription(
        [
            (REGULAR_DRUG, DrugTypeEnum.DIET.value),
            (WHITELIST_DRUG, DrugTypeEnum.DRUG.value),
        ]
    )

    _run_prescalc(prescription.id)

    assert _status(prescription.id) == "0"
    assert _patient_day(prescription.admissionNumber).status == "0"


def test_diet_only_keeps_checked_patient_day(client, analyst_headers, features):
    """A new diet only prescription keeps the checked patient-day."""
    features(DIET_ONLY)
    admission_number = _next_admission_number()
    patient_day = _checked_patient_day(client, analyst_headers, admission_number)

    diet = _create_prescription(
        [(REGULAR_DRUG, DrugTypeEnum.DIET.value)], admission_number=admission_number
    )
    _run_prescalc(diet.id)

    assert _status(diet.id) == "s"
    assert _status(patient_day.id) == "s"


# ─── white list only ──────────────────────────────────────────────────────────


def test_whitelist_feature_off_makes_patient_day_pending(
    client, analyst_headers, features, whitelist_drug
):
    """Without the feature a white list prescription makes the patient-day pending."""
    admission_number = _next_admission_number()
    patient_day = _checked_patient_day(client, analyst_headers, admission_number)

    prescription = _create_prescription(
        [(WHITELIST_DRUG, DrugTypeEnum.DRUG.value)], admission_number=admission_number
    )
    _run_prescalc(prescription.id)

    assert _status(prescription.id) == "0"
    assert _status(patient_day.id) == "0"


def test_whitelist_keeps_checked_patient_day(
    client, analyst_headers, features, whitelist_drug
):
    """A new white list prescription is checked and keeps the checked patient-day."""
    features(WHITELIST_ONLY)
    admission_number = _next_admission_number()
    patient_day = _checked_patient_day(client, analyst_headers, admission_number)

    prescription = _create_prescription(
        [
            (WHITELIST_DRUG, DrugTypeEnum.DRUG.value),
            (REGULAR_DRUG, DrugTypeEnum.DIET.value),
        ],
        admission_number=admission_number,
    )
    _run_prescalc(prescription.id)

    assert _status(prescription.id) == "s"
    assert _status(patient_day.id) == "s"


def test_whitelist_ignores_prescription_with_regular_drug(
    client, analyst_headers, features, whitelist_drug
):
    """A prescription with a drug that is not white list follows the regular flow."""
    features(DIET_ONLY, WHITELIST_ONLY)
    admission_number = _next_admission_number()
    patient_day = _checked_patient_day(client, analyst_headers, admission_number)

    prescription = _create_prescription(
        [
            (WHITELIST_DRUG, DrugTypeEnum.DRUG.value),
            (REGULAR_DRUG, DrugTypeEnum.DRUG.value),
        ],
        admission_number=admission_number,
    )
    _run_prescalc(prescription.id)

    assert _status(prescription.id) == "0"
    assert _status(patient_day.id) == "0"


def test_whitelist_new_item_to_validate_unchecks(
    client, analyst_headers, features, whitelist_drug
):
    """An automatically checked prescription is unchecked when an item to validate arrives."""
    features(WHITELIST_ONLY)
    admission_number = _next_admission_number()
    patient_day = _checked_patient_day(client, analyst_headers, admission_number)

    prescription = _create_prescription(
        [(WHITELIST_DRUG, DrugTypeEnum.DRUG.value)], admission_number=admission_number
    )
    _run_prescalc(prescription.id)
    assert _status(prescription.id) == "s"
    assert _status(patient_day.id) == "s"

    utils_test_prescription.create_prescription_drug(
        id=int(f"{prescription.id}099"),
        idPrescription=prescription.id,
        idDrug=REGULAR_DRUG,
    )
    _run_prescalc(prescription.id)

    assert _status(prescription.id) == "0"
    assert _status(patient_day.id) == "0"
