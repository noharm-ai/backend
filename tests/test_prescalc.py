"""Test: prescalc related tests"""

from datetime import datetime, timedelta

from conftest import session

from models.prescription import Prescription
from static import prescalc
from tests.utils import utils_test_prescription


def test_prescalc(client):
    """Test: execute prescalc and check creation of patient-day prescription"""

    id_prescription = 8001
    admission_number = 10

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

    prescalc(
        {
            "schema": "demo",
            "id_prescription": id_prescription,
            "force": False,
        },
        None,
    )

    assert (
        1
        == session.query(Prescription)
        .filter(Prescription.agg == True)
        .filter(Prescription.admissionNumber == admission_number)
        .count()
    )
