from tests.conftest import session

from models.prescription import Prescription, PrescriptionAudit

PRESCRIPTION_ID = "9199"


def test_get_prescriptions_by_idPrescription_additional2(client, analyst_headers):
    """Teste get /prescriptions/idPrescription - Compara response data com dados do banco e valida status_code 200
    Additional2 idPrescription data validation"""
    response = client.get("/prescriptions/" + PRESCRIPTION_ID, headers=analyst_headers)
    data = response.get_json()["data"]

    assert data["concilia"] == "s"
    assert len(data["prescription"]) == 1
    assert data["prescription"][0]["drug"] == "Medicamento do paciente"
    assert len(data["solution"]) == 0
    assert len(data["procedures"]) == 0
    assert data["birthdate"] == "1941-02-05"


def test_putPrescriprionsCheck(client, analyst_headers):
    """Teste put /prescriptions/idPrescription - Checa o status 's' na prescrição e a existência de um resgistro na tabela prescricao_audit."""
    data = {"status": "s", "idPrescription": PRESCRIPTION_ID}

    response = client.post(
        "/prescriptions/status", json=data, headers=analyst_headers
    )

    prescription = (
        session.query(Prescription)
        .filter(Prescription.id == PRESCRIPTION_ID)
        .filter(Prescription.status == "s")
        .first()
    )
    prescriptionaudit = (
        session.query(PrescriptionAudit)
        .filter(PrescriptionAudit.idPrescription == PRESCRIPTION_ID)
        .filter(PrescriptionAudit.auditType == 1)
        .first()
    )
    assert response.status_code == 200
    assert prescription
    assert prescriptionaudit
