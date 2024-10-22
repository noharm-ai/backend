from conftest import client, get_access, make_headers, pytest
from datetime import datetime

from models.appendix import InterventionReason
from models.prescription import Intervention
from security.role import Role

import json

from tests.utils.utils_test_intervention import (
    dict_expected_before_outcome,
    fields_to_compare_outcome,
    payload_api_set_outcome,
    dict_expected_after_outcome,
    _get_nested_value,
    _compare_specific_fields,
    _compare_json_fields,
)


# Creates new intervention
@pytest.fixture
def test_put_interventions(client):
    """Tests put /intervention  and returns idIntervention"""
    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    data = {
        "idPrescription": "198",
        "idPrescriptionDrug": "54",
        "admissionNumber": 9999,
        "idInterventionReason": [23],
        "reasonDescription": "Substituição",
        "observation": "teste",
        "transcription": "",
        "nonce": 0.13233422355916247,
        "status": "s",
        "version": "1.0",
        "updateResponsible": False,
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


# Retrieve data for concluding the intervention
def test_outcome_data(client, test_put_interventions):
    "Tests /intervention/outcome-data - Checks if the API call for retrieving the data is successful."

    assert test_put_interventions is not None

    data = {"idIntervention": test_put_interventions, "edit": "False"}
    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.get(
        "intervention/outcome-data",
        query_string=data,
        headers=make_headers(access_token),
    )
    response_data = json.loads(response.data)

    # response_data is what we get from the API
    # dict_expected_before_outcome is the  data  that we expect to get from the API, except some fieds conatining dates and ids
    # fields_to_compare is a list of fields that must be compared
    result_compare = _compare_json_fields(
        response_data,
        dict_expected_before_outcome,
        fields_to_compare_outcome,
    )

    assert response.status_code == 200
    assert len(result_compare) == 0


# Finishes the intervention
def test_set_outcome(client, test_put_interventions):
    """Tests  /intervention/set-outcome - Checks if the API call for finishing the intervention is successful."""

    assert test_put_interventions is not None

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


# Checks the outcome result
def test_outcome_data_final(client, test_put_interventions):
    "Tests /intervention/outcome-data - Check if the API call for retrieving the data is successful."

    assert test_put_interventions is not None

    data = {"idIntervention": test_put_interventions, "edit": "False"}
    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.get(
        "intervention/outcome-data",
        query_string=data,
        headers=make_headers(access_token),
    )

    response_data = json.loads(response.data)

    # response_data is what we get from the API
    # dict_expected_after_outcome is the  data  that we expect to get from the API, except some fieds conatining dates and ids
    # fields_to_compare is a list of fields that must be compared
    result_compare = _compare_json_fields(
        response_data,
        dict_expected_after_outcome,
        fields_to_compare_outcome,
    )

    assert response.status_code == 200
    assert len(result_compare) == 0
