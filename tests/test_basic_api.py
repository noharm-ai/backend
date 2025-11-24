import json

from conftest import get_access, make_headers, session
from models.prescription import Prescription, PrescriptionAudit
from security.role import Role
from tests.utils import utils_test_prescription
from static import prescalc

SEGMENT = "1"
DRUG = "5"
PRESCRIPTION = "20"
PRESCRIPTIONDRUG = "20"
ADMISSION = "5"


def test_simple_get(client):
    response = client.get("/version")

    assert response.status_code == 200


def test_getInterventionReasons(client):
    """Teste get /intervention/reasons - Valida o status_code 200."""

    url = "/intervention/reasons"

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.get(url, headers=make_headers(access_token))

    assert response.status_code == 200


def test_getSubstance(client):
    """Teste get /substance - Valida o status_code 200."""

    url = "/substance"

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.get(url, headers=make_headers(access_token))

    assert response.status_code == 200


def test_getDrugs(client):
    """Teste get /drugs/idSegment - Valida o status_code 200."""

    url = f"/drugs/{SEGMENT}"

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.get(url, headers=make_headers(access_token))

    assert response.status_code == 200


def test_getPrescriptionsSegment(client):
    """Teste get /prescriptions?idSegment=idSegment&date=2020-12-31 - Valida o status_code 200."""

    url = f"/prescriptions?idSegment={SEGMENT}&date=2020-12-31"

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.get(url, headers=make_headers(access_token))

    assert response.status_code == 200


def test_getPrescriptions(client):
    """Teste get /prescriptions/idPrescription - Valida o status_code 200."""

    url = f"/prescriptions/{PRESCRIPTION}"

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.get(url, headers=make_headers(access_token))

    assert response.status_code == 200


def test_getPrescriptionsDrug(client):
    """Teste get /prescriptions/drug/idPrescriptionDrug/period - Valida o status_code 200."""

    url = f"/prescriptions/drug/{PRESCRIPTIONDRUG}/period"

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.get(url, headers=make_headers(access_token))

    assert response.status_code == 200


def test_getStaticPrescription(client):
    """Teste get /static/demo/prescription/idPrescription - Valida o status_code 200."""

    response = prescalc(
        {
            "schema": "demo",
            "id_prescription": int(PRESCRIPTION),
            "force": True,
        },
        None,
    )
    response_obj = json.loads(response)

    assert response_obj.get("status", None) == "success"


def test_getExams(client):
    """Teste get /exams/isAdmission - Valida o status_code 200."""

    url = f"/exams/{ADMISSION}"

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.get(url, headers=make_headers(access_token))

    assert response.status_code == 200


def test_getSegments(client):
    """Teste get /segments - Valida o status_code 200."""

    url = "/segments"

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.get(url, headers=make_headers(access_token))

    assert response.status_code == 200


def test_getDepartments(client):
    """Teste get /departments - Valida o status_code 200."""

    url = "/segments/departments"

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.get(url, headers=make_headers(access_token))

    assert response.status_code == 200


def test_get_exam_types(client):
    """Teste get /segments/exams/types - Valida o status_code 200."""

    url = "/admin/exam/types"

    access_token = get_access(client, roles=[Role.CONFIG_MANAGER.value])

    response = client.get(url, headers=make_headers(access_token))

    assert response.status_code == 200


def test_getNotes(client):
    """Teste get /notes/idAdmission - Valida o status_code 200."""

    url = f"/notes/{ADMISSION}/v2"

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.get(url, headers=make_headers(access_token))

    assert response.status_code == 200


def test_putPrescriprionsCheck(client):
    """Teste put /prescriptions/idPrescription - Checa o status "s" na prescrição e a existência de um resgistro na tabela prescricao_audit."""

    url = f"/prescriptions/status"

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    data = {"status": "s", "idPrescription": PRESCRIPTION}

    response = client.post(
        url, data=json.dumps(data), headers=make_headers(access_token)
    )

    assert response.status_code == 200

    prescription = (
        session.query(Prescription)
        .filter(Prescription.id == PRESCRIPTION)
        .filter(Prescription.status == "s")
        .first()
    )
    prescriptionaudit = (
        session.query(PrescriptionAudit)
        .filter(PrescriptionAudit.idPrescription == PRESCRIPTION)
        .filter(PrescriptionAudit.auditType == 1)
        .first()
    )

    assert prescription
    assert prescriptionaudit


def test_putPrescriprionsUncheck(client):
    """Teste put /prescriptions/idPrescription - Checa o status "0" na prescrição e a existência de um resgistro na tabela prescricao_audit."""

    url = f"/prescriptions/status"

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    data = {"status": "0", "idPrescription": PRESCRIPTION}

    response = client.post(
        url, data=json.dumps(data), headers=make_headers(access_token)
    )

    assert response.status_code == 200

    prescription = (
        session.query(Prescription)
        .filter(Prescription.id == PRESCRIPTION)
        .filter(Prescription.status == "0")
        .first()
    )
    prescriptionaudit = (
        session.query(PrescriptionAudit)
        .filter(PrescriptionAudit.idPrescription == PRESCRIPTION)
        .filter(PrescriptionAudit.auditType == "2")
        .first()
    )

    assert prescription
    assert prescriptionaudit


def test_putAggregatePrescriprionsCheckStaging(client):
    """Teste put /prescriptions/idPrescription - Verifica o status "s" e a existência de um resgistro na tabela prescricao_audit
    referente a uma prescrição agregada e todas as dentro dela."""

    id = 2012301000000003
    admissionNumber = 3
    prescriptionid1 = 4
    prescriptionid2 = 7

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    utils_test_prescription.prepare_test_aggregate(
        id, admissionNumber, prescriptionid1, prescriptionid2
    )

    """Criando novamente a prescrição agregada."""

    prescalc(
        {
            "schema": "demo",
            "id_prescription": prescriptionid1,
            "force": True,
        },
        None,
    )

    """Checagem da prescrição agregada."""

    checkagurl = f"/prescriptions/status"

    datachk = {"status": "s", "idPrescription": id}

    client.post(
        checkagurl, data=json.dumps(datachk), headers=make_headers(access_token)
    )

    """Verificação do status esperado em cada prescrição e existência dos
    respectivos registros."""

    pInAg = (
        session.query(Prescription)
        .filter(Prescription.id.in_([prescriptionid1, id]))
        .filter(Prescription.status == "s")
        .all()
    )
    pOutAg = (
        session.query(Prescription)
        .filter(Prescription.id == prescriptionid2)
        .filter(Prescription.status == "0")
        .first()
    )
    pInAgaudit = (
        session.query(PrescriptionAudit)
        .filter(PrescriptionAudit.idPrescription.in_([prescriptionid1, id]))
        .filter(PrescriptionAudit.auditType == 1)
        .all()
    )
    pOutAgaudit = (
        session.query(PrescriptionAudit)
        .filter(PrescriptionAudit.idPrescription == prescriptionid2)
        .filter(PrescriptionAudit.auditType == 1)
        .first()
    )

    assert pOutAg
    assert len(pInAg) == 2
    assert len(pInAgaudit) == 2
    assert not pOutAgaudit


# def test_putAggregatePrescriprionsCheckCpoe(client):
#     """Teste put /prescriptions/idPrescription - Verifica o status "s" e a existência de um resgistro na tabela prescricao_audit
#     referente a uma prescrição agregada e todas as dentro dela."""

#     id = 2012301000000003
#     admissionNumber = 3
#     prescriptionid1 = 4
#     prescriptionid2 = 7

#     access_token = get_access(client, roles=["staging", "cpoe"])

#     utils_test_prescription.prepare_test_aggregate(id, admissionNumber, prescriptionid1, prescriptionid2)

#     pInAg = (
#         session.query(Prescription)
#         .filter(Prescription.id.in_([prescriptionid1, prescriptionid2]))
#         .filter(Prescription.status == "0")
#         .all()
#     )

#     assert len(pInAg) == 2

#     """Criando novamente a prescrição agregada."""

#     createagurl = f"/static/demo/aggregate/3?cpoe=true&p_date=2020-12-30"

#     response = client.get(createagurl, headers=make_headers(access_token))

#     assert response.status_code == 200

#     """Checagem da prescrição agregada."""

#     checkagurl = f"/prescriptions/status"

#     datachk = {"status": "s", "idPrescription": id}

#     response = client.post(
#         checkagurl, data=json.dumps(datachk), headers=make_headers(access_token)
#     )

#     assert response.status_code == 200

#     """Verificação do status esperado em cada prescrição e existência dos
#     respectivos registros."""

#     pInAg = (
#         session.query(Prescription)
#         .filter(Prescription.id.in_([prescriptionid1, prescriptionid2, id]))
#         .filter(Prescription.status == "s")
#         .all()
#     )
#     pInAgaudit = (
#         session.query(PrescriptionAudit)
#         .filter(
#             PrescriptionAudit.idPrescription.in_([prescriptionid1, prescriptionid2, id])
#         )
#         .filter(PrescriptionAudit.auditType == 1)
#         .all()
#     )

#     assert len(pInAg) == 3
#     assert len(pInAgaudit) == 3


def test_putPrescriprions(client):
    """Teste put /prescriptions/idPrescription - Assegura que o usuário com role support não tenha autorização para chamar o endpoint."""

    url = f"/prescriptions/status"

    access_token = get_access(client, roles=[Role.VIEWER.value])

    data = {"status": "s", "idPrescription": PRESCRIPTION}

    response = client.post(
        url, data=json.dumps(data), headers=make_headers(access_token)
    )

    assert response.status_code == 401


def test_postPatient401(client):
    """Teste post /patient/idAdmission - Assegura que o usuário com role readonly não tenha autorização para chamar o endpoint."""

    url = f"/patient/{ADMISSION}"

    access_token = get_access(client, roles=[Role.VIEWER.value])

    data = {"height": 15}

    response = client.post(
        url, data=json.dumps(data), headers=make_headers(access_token)
    )

    assert response.status_code == 401


def test_getPrescriptions404(client):
    """Teste get /prescriptions/404 - Valida o status_code 400."""

    url = "/prescriptions/404"

    access_token = get_access(client, roles=[Role.VIEWER.value])

    response = client.get(url, headers=make_headers(access_token))

    assert response.status_code == 400


def test_putPrescription(client):
    """Teste put /prescriptions/idPrescription - Deve retornar o código 200, indicando funcionamento do endpoint."""

    url = f"/prescriptions/status"

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    data = {"status": "s", "idPrescription": PRESCRIPTION}

    response = client.post(
        url, data=json.dumps(data), headers=make_headers(access_token)
    )

    assert response.status_code == 200


def test_postPatient(client):
    """Teste post /patient/idAsmission - Deve retornar o código 200, indicando funcionamento do endpoint."""

    url = f"/patient/{ADMISSION}"

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    data = {"height": 15}

    response = client.post(
        url, data=json.dumps(data), headers=make_headers(access_token)
    )

    assert response.status_code == 200


def test_putPrescriptionsDrug(client):
    """Teste put /prescriptions/drug/idPrescriptiondrug - Deve retornar o código 200, indicando funcionamento do endpoint."""

    url = f"/prescriptions/drug/{PRESCRIPTIONDRUG}"

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    data = {"notes": "some notes", "admissionNumber": 5}

    response = client.put(
        url, data=json.dumps(data), headers=make_headers(access_token)
    )

    assert response.status_code == 200
