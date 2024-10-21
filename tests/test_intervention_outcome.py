from conftest import *
from datetime import datetime

from models.appendix import InterventionReason
from models.prescription import Intervention
from security.role import Role

import json
from collections.abc import Mapping

# import auxiliary dictionaries to this test
from tests.aux_test_intervention import *


def get_nested_value(data, path):
    keys = path.split(".")
    for key in keys:
        if isinstance(data, Mapping) and key in data:
            data = data[key]
        elif isinstance(data, list) and key.isdigit():
            data = data[int(key)]
        else:
            return None
    return data


def compare_specific_fields(data1, data2, fields_to_compare):
    differences = {}

    for field in fields_to_compare:
        value1 = get_nested_value(data1, field)
        value2 = get_nested_value(data2, field)

        if value1 is None and value2 is None:
            continue
        elif value1 is None:
            differences[field] = ("Field not present in first JSON", value2)
        elif value2 is None:
            differences[field] = (value1, "Field not present in second JSON")
        elif value1 != value2:
            differences[field] = (value1, value2)

    return differences


def compare_json_fields(json_str1, json_str2, fields_to_compare):

    return compare_specific_fields(json_str1, json_str2, fields_to_compare)


# Criar nova intervenção
@pytest.fixture
def test_put_interventions(client):
    """Teste put /intervention  e retorna idIntervention"""
    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])
    idPrescription = "198"
    idPrescriptionDrug = "54"
    admissionNumber = 9999
    idInterventionReason = [23]
    reasonDescription = "Substituição"
    observation = "teste"
    transcription = ""
    nonce = 0.13233422355916247
    status = "s"
    version = "1.0"
    updateResponsible = False
    data = {
        "idPrescription": idPrescription,
        "idPrescriptionDrug": idPrescriptionDrug,
        "admissionNumber": admissionNumber,
        "idInterventionReason": idInterventionReason,
        "reasonDescription": reasonDescription,
        "observation": observation,
        "transcription": transcription,
        "nonce": nonce,
        "status": status,
        "version": version,
        "updateResponsible": updateResponsible,
    }
    url = "/intervention"

    response = client.put(
        url, data=json.dumps(data), headers=make_headers(access_token)
    )

    assert response.status_code == 200

    responseData = json.loads(response.data)["data"]
    idIntervention = responseData[0]["idIntervention"]

    assert idIntervention is not None
    return idIntervention


# Buscar dados para efetivar o desfecho:
def test_outcome_data(client, test_put_interventions):
    "Teste /intervention/outcome-data - Verifica se a chamada da API de leitura de dados é bem sucedida"
    data = {"idIntervention": test_put_interventions, "edit": "False"}
    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.get(
        "intervention/outcome-data",
        query_string=data,
        headers=make_headers(access_token),
    )
    # transforma json string em dicionário
    response_data = json.loads(response.data)

    # dict_esperado é o dicionario que esperamos receber exceto alguns campos com datas e ids
    # fields_to_compare contém os campos que devem ser comparados
    result_compare = compare_json_fields(
        response_data,
        dict_esperado_outcome_data_antes_desfecho,
        fields_to_compare_outcome,
    )

    assert response.status_code == 200
    assert len(result_compare) == 0


# Efetivar o desfecho
def test_set_outcome(client, test_put_interventions):
    """Teste  /intervention/set-outcome - Verifica se a chamada da API é bem sucedida"""

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])
    data = payload_api_set_outcome
    data["idIntervention"] = test_put_interventions
    response = client.post(
        "/intervention/set-outcome",
        data=json.dumps(data),
        headers=make_headers(access_token),
    )
    data = json.loads(response.data)
    assert response.status_code == 200


# Verificar o resultado do desfecho:
def test_outcome_data_desfecho(client, test_put_interventions):
    "Teste /intervention/outcome-data - Verifica se a chamada da API de leitura de dados é bem sucedida"
    data = {"idIntervention": test_put_interventions, "edit": "False"}
    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.get(
        "intervention/outcome-data",
        query_string=data,
        headers=make_headers(access_token),
    )
    # transforma json string em dicionário
    response_data = json.loads(response.data)

    # dict_esperado é o dicionario que esperamos receber exceto alguns campos com datas e ids
    # fields_to_compare contém os campos que devem ser comparados
    result_compare = compare_json_fields(
        response_data,
        dict_esperado_outcome_data_depois_desfecho,
        fields_to_compare_outcome,
    )
    print("RESULT COMPARE: ", result_compare)
    assert response.status_code == 200
    assert len(result_compare) == 0
