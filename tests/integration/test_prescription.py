from tests.conftest import session

from models.prescription import Prescription

PRESCRIPTION = "20"
PRESCRIPTIONDRUG = "20"


def test_get_prescriptions_status_code(client, analyst_headers):
    """Teste get /prescriptions - Valida status_code 200"""
    response = client.get("/prescriptions", headers=analyst_headers)

    assert response.status_code == 200


def test_get_prescriptions_by_idPrescription(client, analyst_headers):
    """Teste get /prescriptions/idPrescription - Compara response data com dados do banco e valida status_code 200"""
    response = client.get("/prescriptions/" + PRESCRIPTION, headers=analyst_headers)
    data = response.get_json()["data"]
    prescription = session.get(Prescription, PRESCRIPTION)

    assert response.status_code == 200
    assert data["idPrescription"] == str(prescription.id)
    assert data["concilia"] == prescription.concilia
    assert data["bed"] == prescription.bed
    assert data["status"] == prescription.status
    assert len(data["prescription"]) > 0


def test_get_prescriptions_by_idPrescription_additional(client, analyst_headers):
    """Teste get /prescriptions/idPrescription - Compara response data com dados do banco e valida status_code 200
    Additional idPrescription data validation"""
    response = client.get("/prescriptions/199", headers=analyst_headers)
    data = response.get_json()["data"]

    assert len(data["prescription"]) == 6
    assert len(data["solution"]) == 0
    assert len(data["procedures"]) == 0
    assert data["birthdate"] == "1941-02-05"


def test_get_prescriptions_drug_by_idPrescription_and_period(client, analyst_headers):
    """Teste get /prescriptions/drug/idPrescription/period - Compara response data com dados do banco e valida status_code 200"""
    response = client.get(
        f"/prescriptions/drug/{PRESCRIPTIONDRUG}/period", headers=analyst_headers
    )

    assert response.status_code == 200


def test_put_prescriptions_by_id(client, analyst_headers):
    """Teste put /prescriptions/id - Compara dados enviados com dados salvos no banco e valida status_code 200"""
    data = {"notes": "note test", "concilia": "s"}
    response = client.put(
        "prescriptions/" + PRESCRIPTION, json=data, headers=analyst_headers
    )
    response_data = response.get_json()["data"]
    prescription = session.get(Prescription, PRESCRIPTION)

    assert response.status_code == 200
    assert response_data == str(prescription.id)
    assert data["notes"] == prescription.notes
    assert data["concilia"] == prescription.concilia


def test_put_prescriptions_by_id_permission(client, viewer_headers):
    """Teste put /prescriptions/id - Deve retornar erro [401 UNAUTHORIZED] devido ao usuário utilizado"""
    data = {"notes": "note test", "concilia": "s"}
    response = client.put(
        "prescriptions/" + PRESCRIPTION, json=data, headers=viewer_headers
    )

    assert response.status_code == 401


def test_get_prescriptions_not_found(client, viewer_headers):
    """Teste get /prescriptions/404 - Valida o status_code 400."""
    response = client.get("/prescriptions/404", headers=viewer_headers)

    assert response.status_code == 400


def test_put_prescriptions_drug(client, analyst_headers):
    """Teste put /prescriptions/drug/idPrescriptiondrug - Deve retornar o código 200, indicando funcionamento do endpoint."""
    data = {"notes": "some notes", "admissionNumber": 5}
    response = client.put(
        f"/prescriptions/drug/{PRESCRIPTIONDRUG}", json=data, headers=analyst_headers
    )

    assert response.status_code == 200
