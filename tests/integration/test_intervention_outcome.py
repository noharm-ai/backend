import pytest
from unittest import TestCase

from tests.utils.utils_test_intervention import (
    dict_expected_before_outcome,
    payload_api_set_outcome,
    dict_expected_after_outcome,
    remove_not_comparable_attributes,
)


# Creates new intervention and returns idIntervention
@pytest.fixture
def created_intervention(client, analyst_headers):
    """Creates a new intervention via PUT /intervention and returns its idIntervention."""
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

    response = client.put("/intervention", json=data, headers=analyst_headers)
    assert response.status_code == 200

    response_data = response.get_json()["data"]
    id_intervention = response_data[0]["idIntervention"]
    assert id_intervention is not None
    return id_intervention


def test_outcome_data(client, analyst_headers, created_intervention):
    """Tests /intervention/outcome-data - Checks retrieval of intervention data before outcome."""
    response = client.get(
        "intervention/outcome-data",
        query_string={"idIntervention": created_intervention, "edit": "False"},
        headers=analyst_headers,
    )
    assert response.status_code == 200

    response_data = response.get_json()
    remove_not_comparable_attributes(response_data)
    remove_not_comparable_attributes(dict_expected_before_outcome)

    TestCase().assertDictEqual(response_data, dict_expected_before_outcome)


def test_set_outcome(client, analyst_headers, created_intervention):
    """Tests /intervention/set-outcome - Checks if finishing the intervention is successful."""
    data = dict(payload_api_set_outcome)
    data["idIntervention"] = created_intervention

    response = client.post("/intervention/set-outcome", json=data, headers=analyst_headers)
    assert response.status_code == 200


def test_outcome_data_final(client, analyst_headers, created_intervention):
    """Tests /intervention/outcome-data - Checks retrieval of intervention data after outcome."""
    response = client.get(
        "intervention/outcome-data",
        query_string={"idIntervention": created_intervention, "edit": "False"},
        headers=analyst_headers,
    )
    assert response.status_code == 200

    response_data = response.get_json()
    remove_not_comparable_attributes(response_data)
    remove_not_comparable_attributes(dict_expected_after_outcome)

    TestCase().assertDictEqual(response_data, dict_expected_before_outcome)
