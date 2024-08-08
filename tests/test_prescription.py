from flask.json import jsonify
from conftest import *
from models.appendix import Department
from models.segment import Segment

# from models.prescription import Prescription

from models.prescription import Prescription

# def pres_getall():
#   pres = Prescription()
#   pres.id = 1
#   pres.idHospital = 1
#   pres.name = 'pres'
#   return [pres, pres]


def test_get_prescriptions_status_code(client):
    """Teste get /prescriptions - Valida status_code 200"""
    access_token = get_access(client)

    response = client.get("/prescriptions", headers=make_headers(access_token))

    assert response.status_code == 200


def test_get_prescriptions_by_idPrescription(client):
    """Teste get /prescriptions/idPrescription - Compara response data com dados do banco e valida status_code 200"""

    access_token = get_access(client)

    idPrescription = "20"

    response = client.get(
        "/prescriptions/" + idPrescription, headers=make_headers(access_token)
    )
    data = json.loads(response.data)["data"]
    prescription = session.query(Prescription).get(idPrescription)

    assert response.status_code == 200
    assert data["idPrescription"] == str(prescription.id)
    assert data["concilia"] == prescription.concilia
    assert data["bed"] == prescription.bed
    assert data["status"] == prescription.status
    assert len(data["prescription"]) > 0
    


def test_get_prescriptions_by_idPrescription_additional(client):
    """Teste get /prescriptions/idPrescription - Compara response data com dados do banco e valida status_code 200
       Additional idPrescription data validation"""

    access_token = get_access(client)

    idPrescription = "199"

    response = client.get(
        "/prescriptions/" + idPrescription, headers=make_headers(access_token)
    )
    data = json.loads(response.data)["data"]
    
    assert len(data['prescription']) == 6
    assert len(data['solution']) == 0
    assert len(data['procedures']) == 0
    assert data['birthdate'] == '1941-02-05'

def test_get_prescriptions_by_idPrescription_additional2(client):
    """Teste get /prescriptions/idPrescription - Compara response data com dados do banco e valida status_code 200
       Additional2 idPrescription data validation"""

    access_token = get_access(client)

    idPrescription = "9199"

    response = client.get(
        "/prescriptions/" + idPrescription, headers=make_headers(access_token)
    )
    data = json.loads(response.data)["data"]
    
    assert data['concilia'] == 's'
    assert len(data['prescription']) == 1
    assert data['prescription'][0]['drug'] == 'Medicamento do paciente'
    assert len(data['solution']) == 0
    assert len(data['procedures']) == 0
    assert data['birthdate']   ==  "1941-02-05"


def test_get_prescriptions_drug_by_idPrescription_and_period(client):
    """Teste get /prescriptions/drug/idPrescription/period - Compara response data com dados do banco e valida status_code 200"""

    access_token = get_access(client)

    idPrescription = "20"

    url = "/prescriptions/drug/{0}/period".format(idPrescription)

    response = client.get(url, headers=make_headers(access_token))
    data = json.loads(response.data)["data"]
    # TODO: Add consulta ao banco de dados e comparar retorno (retornando status 200 porém data = [])

    assert response.status_code == 200

def test_putPrescriprionsCheck(client):
    """Teste put /prescriptions/idPrescription - Checa o status "s" na prescrição e a existência de um resgistro na tabela prescricao_audit."""

    url = f"/prescriptions/status"

    access_token = get_access(client, roles=["staging"])

    data = {"status": "s", "idPrescription": 9199}

    response = client.post(
        url, data=json.dumps(data), headers=make_headers(access_token)
    )
    
    prescription = (
        session.query(Prescription)
        .filter(Prescription.id == 9199)
        .filter(Prescription.status == "s")
        .first()
    )
    prescriptionaudit = (
        session.query(PrescriptionAudit)
        .filter(PrescriptionAudit.idPrescription == 9199)
        .filter(PrescriptionAudit.auditType == 1)
        .first()
    )
    assert response.status_code == 200
    assert prescription
    assert prescriptionaudit

def test_put_prescriptions_by_id(client):
    """Teste put /prescriptions/id - Compara dados enviados com dados salvos no banco e valida status_code 200"""

    access_token = get_access(client, roles=["staging"])

    idPrescription = "20"
    data = {"notes": "note test", "concilia": "s"}
    url = "prescriptions/" + idPrescription

    response = client.put(
        url, data=json.dumps(data), headers=make_headers(access_token)
    )
    responseData = json.loads(response.data)["data"]
    prescription = session.query(Prescription).get(idPrescription)

    assert response.status_code == 200
    assert responseData == str(prescription.id)
    assert data["notes"] == prescription.notes
    assert data["concilia"] == prescription.concilia


def test_put_prescriptions_by_id_permission(client):
    """Teste put /prescriptions/id - Deve retornar erro [401 UNAUTHORIZED] devido ao usuário utilizado"""

    access_token = get_access(client)

    idPrescription = "20"
    data = {"notes": "note test", "concilia": "s"}
    url = "prescriptions/" + idPrescription

    response = client.put(
        url, data=json.dumps(data), headers=make_headers(access_token)
    )

    assert response.status_code == 401


def test_get_static_demo_prescription_by_idPrescription(client):
    """Teste get /static/demo/prescription/idPrescription - Valida status_code 200"""
    access_token = get_access(client)

    idPrescription = "20"

    response = client.get(
        "static/demo/prescription/" + idPrescription, headers=make_headers(access_token)
    )
    data = json.loads(response.data)
    # TODO: Add consulta ao banco de dados e comparar retorno (retornando status 200 porém data = 20)

    assert response.status_code == 200
