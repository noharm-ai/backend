"""Test: prescalc related tests"""

import json
from datetime import datetime, timedelta
from typing import Union

from conftest import get_access, make_headers, session, session_commit

from models.prescription import Prescription
from security.role import Role
from static import prescalc
from tests.utils import utils_test_prescription

# Use mutable object to track counters across function calls
test_counters = {"id_prescription": 100000, "admission_number": 100000}


def _insert_basic_prescription(
    admission_number: Union[int, None] = None,
) -> Prescription:
    """Creates a basic prescription with two drugs"""

    prescription = utils_test_prescription.create_prescription(
        id=test_counters["id_prescription"],
        admissionNumber=admission_number
        if admission_number is not None
        else test_counters["admission_number"],
        idPatient=1,
        date=datetime.now(),
        expire=datetime.now() + timedelta(days=1),
    )

    id_prescription_drug = int(f"{test_counters['id_prescription']}001")

    utils_test_prescription.create_prescription_drug(
        id=id_prescription_drug,
        idPrescription=test_counters["id_prescription"],
        idDrug=3,
    )

    utils_test_prescription.create_prescription_drug(
        id=id_prescription_drug + 1,
        idPrescription=test_counters["id_prescription"],
        idDrug=4,
    )

    test_counters["id_prescription"] += 1
    test_counters["admission_number"] += 1

    return prescription


def test_prescalc_flow(client):
    """Test:
    1) execute prescalc
    2) assert creation of patient-day prescription
    3) check patient-day
    4) add items
    5) run prescalc again
    6) check if patient-day check is rolled back
    7) check if individual prescription status is rolled back
    """

    prescription = _insert_basic_prescription()

    # 1) execute prescalc
    prescalc(
        {
            "schema": "demo",
            "id_prescription": prescription.id,
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
        id=int(f"{prescription.id}003"), idPrescription=prescription.id, idDrug=5
    )
    utils_test_prescription.create_prescription_drug(
        id=int(f"{prescription.id}004"), idPrescription=prescription.id, idDrug=6
    )

    # 5) execute prescalc again
    prescalc(
        {
            "schema": "demo",
            "id_prescription": prescription.id,
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

    # 7) check if individual prescription status is rolled back
    prescription = (
        session.query(Prescription).filter(Prescription.id == prescription.id).first()
    )

    assert prescription is not None
    assert prescription.status == "0"


def test_prescalc_flow2(client):
    """Test when prescription check happens before prescalc
    1) check individual prescription
    2) assert creation of patient-day prescription
    3) check patient-day created
    4) check individual prescriptions status, must be 's'because it was checked before prescalc
    """

    prescription = _insert_basic_prescription()

    # 1) start checking individual prescription
    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])
    payload = {"status": "s", "idPrescription": prescription.id}

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
            "id_prescription": prescription.id,
            "force": False,
        },
        None,
    )

    session_commit()

    # 3) check if patient-day is created
    patient_day = (
        session.query(Prescription)
        .filter(Prescription.agg)
        .filter(Prescription.admissionNumber == prescription.admissionNumber)
        .first()
    )

    assert patient_day is not None
    assert patient_day.status == "0"

    # 4) verify individual prescription status
    prescription = (
        session.query(Prescription)
        .filter(Prescription.id == prescription.admissionNumber)
        .first()
    )

    assert prescription is not None
    assert prescription.status == "s"


def test_prescalc_flow3(client):
    """Test:
    1) execute prescalc
    2) assert creation of patient-day prescription
    3) check patient-day
    4) run prescalc again
    5) check if patient-day kept its status
    6) check if individual kept its status
    """

    prescription = _insert_basic_prescription()

    # 1) execute prescalc
    prescalc(
        {
            "schema": "demo",
            "id_prescription": prescription.id,
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

    # 4) execute prescalc again
    prescalc(
        {
            "schema": "demo",
            "id_prescription": prescription.id,
            "force": False,
        },
        None,
    )

    session_commit()

    # 6) check if patient-day kept its status
    patient_day = (
        session.query(Prescription).filter(Prescription.id == patient_day.id).first()
    )

    assert patient_day is not None
    assert patient_day.status == "s"

    # 7) check if individual prescription kept its status
    prescription = (
        session.query(Prescription).filter(Prescription.id == prescription.id).first()
    )

    assert prescription is not None
    assert prescription.status == "s"


def test_prescalc_flow4(client):
    """Test:
    1) execute prescalc
    2) assert creation of patient-day prescription
    3) check patient-day
    4) add new prescription
    5) run prescalc for new prescription
    6) check if patient-day status is rolled back
    7) check if first individual kept its status
    """

    prescription = _insert_basic_prescription()

    # 1) execute prescalc
    prescalc(
        {
            "schema": "demo",
            "id_prescription": prescription.id,
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

    # 4) add new prescription
    new_prescription = _insert_basic_prescription(
        admission_number=patient_day.admissionNumber
    )

    prescalc(
        {
            "schema": "demo",
            "id_prescription": new_prescription.id,
            "force": False,
        },
        None,
    )

    session_commit()

    # 5) run prescalc for new prescription
    prescalc(
        {
            "schema": "demo",
            "id_prescription": new_prescription.id,
            "force": False,
        },
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
