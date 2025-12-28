"""Test: prescalc related tests"""

import json
from datetime import datetime, timedelta

from conftest import get_access, make_headers, session, session_commit

from models.prescription import Prescription
from security.role import Role
from static import prescalc
from tests.utils import utils_test_prescription


def test_prescalc_flow(client):
    """Test:
    1) execute prescalc
    2) assert creation of patient-day prescription
    3) check patient-day
    4) add items
    5) run prescalc again
    6) check if patient-day check is rolled back
    """

    id_prescription = 7001
    admission_number = 11

    utils_test_prescription.create_prescription(
        id=id_prescription,
        admissionNumber=admission_number,
        idPatient=1,
        date=datetime.now(),
        expire=datetime.now() + timedelta(days=1),
    )

    utils_test_prescription.create_prescription_drug(
        id=7001001, idPrescription=id_prescription, idDrug=3
    )

    utils_test_prescription.create_prescription_drug(
        id=7001002, idPrescription=id_prescription, idDrug=4
    )

    # 1) execute prescalc
    prescalc(
        {
            "schema": "demo",
            "id_prescription": id_prescription,
            "force": False,
        },
        None,
    )

    patient_day = (
        session.query(Prescription)
        .filter(Prescription.agg)
        .filter(Prescription.admissionNumber == admission_number)
        .first()
    )

    # 2) assert creation of patient-day prescription
    assert patient_day is not None

    # 3) check patient-day
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

    # 4) add items
    utils_test_prescription.create_prescription_drug(
        id=7001003, idPrescription=id_prescription, idDrug=5
    )
    utils_test_prescription.create_prescription_drug(
        id=7001004, idPrescription=id_prescription, idDrug=6
    )

    # 5) execute prescalc again
    prescalc(
        {
            "schema": "demo",
            "id_prescription": id_prescription,
            "force": False,
        },
        None,
    )

    session_commit()

    # 6) check if patient-day status is rolled back
    patient_day = (
        session.query(Prescription).filter(Prescription.id == patient_day.id).first()
    )

    assert patient_day is not None
    assert patient_day.status == "0"


def test_prescalc_flow2(client):
    """Test when prescription check happens before prescalc
    1) check individual prescription
    2) assert creation of patient-day prescription
    3) check patient-day created
    4) check individual prescriptions status, must be 's'because it was checked before prescalc
    """

    id_prescription = 8001
    admission_number = 12

    utils_test_prescription.create_prescription(
        id=id_prescription,
        admissionNumber=admission_number,
        idPatient=1,
        date=datetime.now(),
        expire=datetime.now() + timedelta(days=1),
    )

    utils_test_prescription.create_prescription_drug(
        id=8001001, idPrescription=id_prescription, idDrug=3
    )

    utils_test_prescription.create_prescription_drug(
        id=8001002, idPrescription=id_prescription, idDrug=4
    )

    # 1) start checking individual prescription
    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])
    payload = {"status": "s", "idPrescription": id_prescription}

    response = client.post(
        "/prescriptions/status",
        data=json.dumps(payload),
        headers=make_headers(access_token),
    )

    assert response.status_code == 200

    session_commit()

    # 2) run prescalc
    prescalc(
        {
            "schema": "demo",
            "id_prescription": id_prescription,
            "force": False,
        },
        None,
    )

    session_commit()

    # 3) check if patient-day is created
    patient_day = (
        session.query(Prescription)
        .filter(Prescription.agg)
        .filter(Prescription.admissionNumber == admission_number)
        .first()
    )

    assert patient_day is not None
    assert patient_day.status == "0"

    # 4) verify individual prescription status
    prescription = (
        session.query(Prescription).filter(Prescription.id == id_prescription).first()
    )

    assert prescription is not None
    assert prescription.status == "s"
