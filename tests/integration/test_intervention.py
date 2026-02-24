from datetime import datetime

from tests.conftest import session

from models.appendix import InterventionReason
from models.prescription import Intervention


def test_get_interventions(client, analyst_headers):
    """Teste get /intervention/search - Compara quantidade de intervenções enviadas com quantidade salva no banco e valida status_code 200"""
    data = {"startDate": datetime.today().isoformat()}
    response = client.post(
        "/intervention/search", json=data, headers=analyst_headers
    )

    assert response.status_code == 200


def test_get_interventions_by_reason(client, analyst_headers):
    """Teste get /intervention/reasons - Compara quantidade de rasões enviadas com quantidade salva no banco e valida status_code 200"""
    qty_reasons = session.query(InterventionReason).count()
    response = client.get("/intervention/reasons", headers=analyst_headers)
    data = response.get_json()["data"]

    assert response.status_code == 200
    assert qty_reasons == len(data)


def test_put_interventions(client, analyst_headers):
    """Teste put /intervention - Compara dados enviados com dados salvos no banco e valida status_code 200"""
    id_prescription_drug = "1"
    data = {
        "status": "s",
        "admissionNumber": 5,
        "idInterventionReason": [5],
        "error": False,
        "cost": False,
        "observation": "teste observations",
        "interactions": [5],
        "idPrescriptionDrug": id_prescription_drug,
    }

    response = client.put("/intervention", json=data, headers=analyst_headers)
    assert response.status_code == 200

    response_data = response.get_json()["data"]
    intervention = (
        session.query(Intervention)
        .filter(Intervention.idIntervention == response_data[0]["idIntervention"])
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


def test_put_interventions_permission(client, viewer_headers):
    """Teste put /intervention - Deve retornar erro [401 UNAUTHORIZED] devido ao usuário utilizado"""
    data = {
        "status": "s",
        "admissionNumber": "5",
        "idIntervention": "1",
        "idPrescription": "0",
    }

    response = client.put("/intervention", json=data, headers=viewer_headers)

    assert response.status_code == 401
