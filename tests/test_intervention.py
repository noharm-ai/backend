from conftest import *
from datetime import datetime

from models.appendix import InterventionReason
from models.prescription import Intervention


def test_get_interventions(client):
    """Teste get /intervention/search - Compara quantidade de intervenções enviadas com quantidade salva no banco e valida status_code 200"""

    access_token = get_access(client)
    interventions = session.query(Intervention).count()

    data = {"startDate": datetime.today().isoformat()}

    response = client.post(
        "/intervention/search",
        data=json.dumps(data),
        headers=make_headers(access_token),
    )
    data = json.loads(response.data)["data"]
    # TODO: Add consulta ao banco de dados e comparar count de intervenções

    assert response.status_code == 200


def test_get_interventions_by_reason(client):
    """Teste get /intervention/reasons - Compara quantidade de rasões enviadas com quantidade salva no banco e valida status_code 200"""

    access_token = get_access(client)
    qtdReasons = session.query(InterventionReason).count()

    response = client.get("/intervention/reasons", headers=make_headers(access_token))
    data = json.loads(response.data)["data"]

    assert response.status_code == 200
    assert qtdReasons == len(data)


def test_put_interventions(client):
    """Teste put /intervention - Compara dados enviados com dados salvos no banco e valida status_code 200"""

    access_token = get_access(client, roles=["staging"])

    idPrescriptionDrug = "99"
    data = {
        "status": "s",
        "admissionNumber": 5,
        "idInterventionReason": [5],
        "error": False,
        "cost": False,
        "observation": "teste observations",
        "interactions": [5],
        "idPrescriptionDrug": idPrescriptionDrug,
    }
    url = "/intervention"

    response = client.put(
        url, data=json.dumps(data), headers=make_headers(access_token)
    )

    assert response.status_code == 200

    responseData = json.loads(response.data)["data"]

    intervention = (
        session.query(Intervention)
        .filter(Intervention.idIntervention == responseData[0]["idIntervention"])
        .first()
    )

    assert intervention is not None
    assert intervention.status == data["status"]
    assert intervention.admissionNumber == data["admissionNumber"]
    assert intervention.idInterventionReason == data["idInterventionReason"]
    assert intervention.error == data["error"]
    assert intervention.cost == data["cost"]
    assert intervention.notes == data["observation"]
    assert intervention.interactions == data["interactions"]


def test_put_interventions_permission(client):
    """Teste put /intervention - Deve retornar erro [401 UNAUTHORIZED] devido ao usuário utilizado"""

    access_token = get_access(client, roles=["suporte"])

    idIntervention = "1"
    idPrescription = "0"
    data = {
        "status": "s",
        "admissionNumber": "5",
        "idIntervention": idIntervention,
        "idPrescription": idPrescription,
    }

    url = "/intervention"

    response = client.put(
        url, data=json.dumps(data), headers=make_headers(access_token)
    )

    assert response.status_code == 401
