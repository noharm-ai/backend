import json

from conftest import *
from security.role import Role


def test_set_outcome(client):
    """Teste  /intervention/set-outcome - Verifica se a chamada da API é bem sucedida"""

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])
    data = {
        "idIntervention": 1,
        "outcome": "a",
        "economyDayAmount": 5,
        "economyDayAmountManual": False,
        "economyDayValue": 100.50,
        "economyDayValueManual": False,
        "idPrescriptionDrugDestiny": 456,
        "origin": {"key1": "value1", "key2": "value2"},
        "destiny": {"key3": "value3", "key4": "value4"},
    }

    response = client.post(
        "/intervention/set-outcome",
        data=json.dumps(data),
        headers=make_headers(access_token),
    )
    data = json.loads(response.data)

    # Assert response structure
    assert response.status_code == 200
    assert "data" in data
    assert "status" in data

    # Assert response output content
    assert data["data"] == True
    assert data["status"] == "success"


def test_outcome_data(client):
    """Teste /intervention/outcome-data - Verifica se a chamada da API de leitura de dados é bem sucedida"""
    data = {"idIntervention": 14, "edit": "False"}
    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.get(
        "intervention/outcome-data",
        query_string=data,
        headers=make_headers(access_token),
    )
    data = json.loads(response.data)["data"]

    # Assert response structure
    assert response.status_code == 200
    assert "date" in data["header"]
    assert "outcomeAt" in data["header"]
    assert "idIntervention" in data

    # Assert response output content
    # To do
