"""Test: prescalc related tests"""

import json

from conftest import get_access, make_headers, session, session_commit

from models.prescription import Prescription
from security.role import Role
from static import atendcalc
from tests.utils import utils_test_prescription


def test_atendcalc_flow(client):
    """Test:
    1) execute atendcalc
    2) assert creation of patient-day prescription
    3) check patient-day
    4) check if patient-day check is rolled back
    5) check if individual prescription kept its status
    """

    prescription = utils_test_prescription.create_basic_prescription(cpoe=True)

    # 1) execute prescalc
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

    # # 3) check patient-day
    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])
    payload = {"status": "s", "idPrescription": patient_day.id}

    response = client.post(
        "/prescriptions/status",
        data=json.dumps(payload),
        headers=make_headers(access_token),
    )

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
