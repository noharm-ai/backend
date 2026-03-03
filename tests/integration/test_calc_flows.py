"""Tests: Prescription calculation flows (prescalc and atendcalc)"""

import json

from tests.conftest import session, session_commit

from models.prescription import Prescription
from static import atendcalc, prescalc
from tests.utils import utils_test_prescription


# ─── prescalc static ──────────────────────────────────────────────────────────


def test_prescalc_static():
    """Teste prescalc direto - Valida retorno 'success' do prescalc para a prescrição de seed."""
    response = prescalc(
        {"schema": "demo", "id_prescription": 20, "force": True},
        None,
    )
    response_obj = json.loads(response)

    assert response_obj.get("status") == "success"


# ─── prescalc (cpoe=False) ────────────────────────────────────────────────────


def test_prescalc_flow(client, analyst_headers):
    """Test:
    1) execute prescalc
    2) assert creation of patient-day prescription
    3) check patient-day
    4) add items
    5) run prescalc again
    6) check if patient-day check is rolled back
    7) check if individual prescription status is rolled back
    """

    prescription = utils_test_prescription.create_basic_prescription()

    # 1) execute prescalc
    prescalc(
        {"schema": "demo", "id_prescription": prescription.id, "force": False},
        None,
    )

    patient_day = (
        session.query(Prescription)
        .filter(Prescription.agg)
        .filter(Prescription.admissionNumber == prescription.admissionNumber)
        .first()
    )

    # 2) assert creation of patient-day prescription
    assert patient_day is not None

    # 3) check patient-day
    payload = {"status": "s", "idPrescription": patient_day.id}
    response = client.post("/prescriptions/status", json=payload, headers=analyst_headers)
    assert response.status_code == 200

    session_commit()

    patient_day = (
        session.query(Prescription).filter(Prescription.id == patient_day.id).first()
    )
    assert patient_day is not None
    assert patient_day.status == "s"

    # 4) add items
    utils_test_prescription.create_prescription_drug(
        id=int(f"{prescription.id}003"), idPrescription=prescription.id, idDrug=5
    )
    utils_test_prescription.create_prescription_drug(
        id=int(f"{prescription.id}004"), idPrescription=prescription.id, idDrug=6
    )

    # 5) execute prescalc again
    prescalc(
        {"schema": "demo", "id_prescription": prescription.id, "force": False},
        None,
    )

    session_commit()

    # 6) check if patient-day status is rolled back
    patient_day = (
        session.query(Prescription).filter(Prescription.id == patient_day.id).first()
    )
    assert patient_day is not None
    assert patient_day.status == "0"

    # 7) check if individual prescription status is rolled back
    prescription = (
        session.query(Prescription).filter(Prescription.id == prescription.id).first()
    )
    assert prescription is not None
    assert prescription.status == "0"


def test_prescalc_flow2(client, analyst_headers):
    """Test when prescription check happens before prescalc, items unchanged
    1) check individual prescription
    2) run prescalc
    3) patient-day must be created with status 's' (inherited from checked individual)
    4) individual prescription must remain 's'
    """

    prescription = utils_test_prescription.create_basic_prescription()

    # 1) check individual prescription before prescalc runs
    payload = {"status": "s", "idPrescription": prescription.id}
    response = client.post("/prescriptions/status", json=payload, headers=analyst_headers)
    assert response.status_code == 200

    session_commit()

    # 2) run prescalc
    prescalc(
        {"schema": "demo", "id_prescription": prescription.id, "force": False},
        None,
    )

    session_commit()

    # 3) patient-day must be created with 's' (items unchanged, check is still valid)
    patient_day = (
        session.query(Prescription)
        .filter(Prescription.agg)
        .filter(Prescription.admissionNumber == prescription.admissionNumber)
        .first()
    )
    assert patient_day is not None
    assert patient_day.status == "s"

    # 4) individual prescription must remain checked
    prescription = (
        session.query(Prescription).filter(Prescription.id == prescription.id).first()
    )
    assert prescription is not None
    assert prescription.status == "s"


def test_prescalc_flow2b(client, analyst_headers):
    """Test when prescription check happens before prescalc, but items changed
    1) check individual prescription
    2) add more items to the prescription
    3) run prescalc
    4) patient-day must be created with status '0' (items changed, check invalidated)
    5) individual prescription must be rolled back to '0'
    """

    prescription = utils_test_prescription.create_basic_prescription()

    # 1) check individual prescription before prescalc runs
    payload = {"status": "s", "idPrescription": prescription.id}
    response = client.post("/prescriptions/status", json=payload, headers=analyst_headers)
    assert response.status_code == 200

    session_commit()

    # 2) add more items after the check
    utils_test_prescription.create_prescription_drug(
        id=int(f"{prescription.id}003"), idPrescription=prescription.id, idDrug=5
    )
    utils_test_prescription.create_prescription_drug(
        id=int(f"{prescription.id}004"), idPrescription=prescription.id, idDrug=6
    )

    # 3) run prescalc
    prescalc(
        {"schema": "demo", "id_prescription": prescription.id, "force": False},
        None,
    )

    session_commit()

    # 4) patient-day must be unchecked (item count changed, check invalidated)
    patient_day = (
        session.query(Prescription)
        .filter(Prescription.agg)
        .filter(Prescription.admissionNumber == prescription.admissionNumber)
        .first()
    )
    assert patient_day is not None
    assert patient_day.status == "0"

    # 5) individual prescription must also be rolled back
    prescription = (
        session.query(Prescription).filter(Prescription.id == prescription.id).first()
    )
    assert prescription is not None
    assert prescription.status == "0"


def test_prescalc_flow3(client, analyst_headers):
    """Test:
    1) execute prescalc
    2) assert creation of patient-day prescription
    3) check patient-day
    4) run prescalc again
    5) check if patient-day kept its status
    6) check if individual kept its status
    """

    prescription = utils_test_prescription.create_basic_prescription()

    # 1) execute prescalc
    prescalc(
        {"schema": "demo", "id_prescription": prescription.id, "force": False},
        None,
    )

    patient_day = (
        session.query(Prescription)
        .filter(Prescription.agg)
        .filter(Prescription.admissionNumber == prescription.admissionNumber)
        .first()
    )

    # 2) assert creation of patient-day prescription
    assert patient_day is not None

    # 3) check patient-day
    payload = {"status": "s", "idPrescription": patient_day.id}
    response = client.post("/prescriptions/status", json=payload, headers=analyst_headers)
    assert response.status_code == 200

    session_commit()

    patient_day = (
        session.query(Prescription).filter(Prescription.id == patient_day.id).first()
    )
    assert patient_day is not None
    assert patient_day.status == "s"

    # 4) execute prescalc again
    prescalc(
        {"schema": "demo", "id_prescription": prescription.id, "force": False},
        None,
    )

    session_commit()

    # 5) check if patient-day kept its status
    patient_day = (
        session.query(Prescription).filter(Prescription.id == patient_day.id).first()
    )
    assert patient_day is not None
    assert patient_day.status == "s"

    # 6) check if individual prescription kept its status
    prescription = (
        session.query(Prescription).filter(Prescription.id == prescription.id).first()
    )
    assert prescription is not None
    assert prescription.status == "s"


def test_prescalc_flow4(client, analyst_headers):
    """Test:
    1) execute prescalc
    2) assert creation of patient-day prescription
    3) check patient-day
    4) add new prescription
    5) run prescalc for new prescription
    6) check if patient-day status is rolled back
    7) check if first individual kept its status
    """

    prescription = utils_test_prescription.create_basic_prescription()

    # 1) execute prescalc
    prescalc(
        {"schema": "demo", "id_prescription": prescription.id, "force": False},
        None,
    )

    patient_day = (
        session.query(Prescription)
        .filter(Prescription.agg)
        .filter(Prescription.admissionNumber == prescription.admissionNumber)
        .first()
    )

    # 2) assert creation of patient-day prescription
    assert patient_day is not None

    # 3) check patient-day
    payload = {"status": "s", "idPrescription": patient_day.id}
    response = client.post("/prescriptions/status", json=payload, headers=analyst_headers)
    assert response.status_code == 200

    session_commit()

    patient_day = (
        session.query(Prescription).filter(Prescription.id == patient_day.id).first()
    )
    assert patient_day is not None
    assert patient_day.status == "s"

    # 4) add new prescription
    new_prescription = utils_test_prescription.create_basic_prescription(
        admission_number=patient_day.admissionNumber
    )

    prescalc(
        {"schema": "demo", "id_prescription": new_prescription.id, "force": False},
        None,
    )

    session_commit()

    # 5) run prescalc for new prescription
    prescalc(
        {"schema": "demo", "id_prescription": new_prescription.id, "force": False},
        None,
    )

    # 6) check if patient-day status is rolled back
    patient_day = (
        session.query(Prescription).filter(Prescription.id == patient_day.id).first()
    )
    assert patient_day is not None
    assert patient_day.status == "0"

    # 7) check if first individual kept its status
    prescription = (
        session.query(Prescription).filter(Prescription.id == prescription.id).first()
    )
    assert prescription is not None
    assert prescription.status == "s"


# ─── atendcalc (cpoe=True) ────────────────────────────────────────────────────


def test_atendcalc_flow(client, analyst_headers):
    """Test:
    1) execute atendcalc
    2) assert creation of patient-day prescription
    3) check patient-day
    4) check if patient-day check is rolled back
    5) check if individual prescription kept its status
    """

    prescription = utils_test_prescription.create_basic_prescription(cpoe=True)

    # 1) execute atendcalc
    atendcalc(
        {
            "schema": "demo",
            "admission_number": prescription.admissionNumber,
            "force": False,
        },
        None,
    )

    patient_day = (
        session.query(Prescription)
        .filter(Prescription.agg)
        .filter(Prescription.admissionNumber == prescription.admissionNumber)
        .first()
    )

    # 2) assert creation of patient-day prescription
    assert patient_day is not None
    assert patient_day.status == "0"

    # 3) check patient-day
    payload = {"status": "s", "idPrescription": patient_day.id}
    response = client.post("/prescriptions/status", json=payload, headers=analyst_headers)
    assert response.status_code == 200

    session_commit()

    patient_day = (
        session.query(Prescription).filter(Prescription.id == patient_day.id).first()
    )
    assert patient_day is not None
    assert patient_day.status == "s"

    # 4) add items (trigger should roll back prescription check)
    utils_test_prescription.create_prescription_drug(
        id=int(f"{prescription.id}003"), idPrescription=prescription.id, idDrug=5
    )
    utils_test_prescription.create_prescription_drug(
        id=int(f"{prescription.id}004"), idPrescription=prescription.id, idDrug=6
    )

    session_commit()

    # 5) check if patient-day status is rolled back
    patient_day = (
        session.query(Prescription).filter(Prescription.id == patient_day.id).first()
    )
    assert patient_day is not None
    assert patient_day.status == "0"

    # 6) check if individual prescription kept its status
    prescription = (
        session.query(Prescription).filter(Prescription.id == prescription.id).first()
    )
    assert prescription is not None
    assert prescription.status == "s"
