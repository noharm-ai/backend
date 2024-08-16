from conftest import *

from models.prescription import Prescription


def test_get_prescriptions_by_idPrescription_additional2(client):
    """Teste get /prescriptions/idPrescription - Compara response data com dados do banco e valida status_code 200
    Additional2 idPrescription data validation"""

    access_token = get_access(client)
    idPrescription = "9199"

    response = client.get(
        "/prescriptions/" + idPrescription, headers=make_headers(access_token)
    )
    data = json.loads(response.data)["data"]

    assert data["concilia"] == "s"
    assert len(data["prescription"]) == 1
    assert data["prescription"][0]["drug"] == "Medicamento do paciente"
    assert len(data["solution"]) == 0
    assert len(data["procedures"]) == 0
    assert data["birthdate"] == "1941-02-05"


def test_putPrescriprionsCheck(client):
    """Teste put /prescriptions/idPrescription - Checa o status "s" na prescrição e a existência de um resgistro na tabela prescricao_audit."""

    url = f"/prescriptions/status"
    access_token = get_access(client, roles=["staging"])
    PRESCRIPTION_ID = "9199"
    data = {"status": "s", "idPrescription": PRESCRIPTION_ID}

    response = client.post(
        url, data=json.dumps(data), headers=make_headers(access_token)
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
