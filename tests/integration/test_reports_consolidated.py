"""Tests: POST /reports/consolidated/economy, /intervention, /patient-day and /prescription

The consolidated reports delegate the heavy lifting to the private backend
lambda, which is short-circuited in the TEST environment. What is worth
pinning down here is the permission gate and the request validation.
"""

import pytest

from tests.conftest import get_access, make_headers
from security.role import Role
from utils import status

URL = "/reports/consolidated/economy"
INTERVENTION_URL = "/reports/consolidated/intervention"
PATIENT_DAY_URL = "/reports/consolidated/patient-day"
PRESCRIPTION_URL = "/reports/consolidated/prescription"


def test_economy_report_permission_denied(client):
    """A user without READ_REPORTS cannot open the consolidated economy report."""
    headers = make_headers(
        get_access(client, roles=[Role.DISPENSING_MANAGER.value])
    )

    response = client.post(URL, json={"year": 2026}, headers=headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_economy_report_requires_year(client, analyst_headers):
    """The request body must carry a year [400 BAD REQUEST]."""
    response = client.post(URL, json={"segment": ["Adulto"]}, headers=analyst_headers)

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_economy_report_accepts_full_filter_set(client, analyst_headers):
    """A valid request with every optional filter is accepted [200 OK]."""
    payload = {
        "year": 2026,
        "department": ["UTI"],
        "segment": ["Adulto"],
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "economy_type": [1, 2],
        "status": ["a"],
        "responsible": ["Fulano Beltrano"],
        "economy_value_type": "p",
    }

    response = client.post(URL, json=payload, headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["status"] == "success"


def test_intervention_report_permission_denied(client):
    """A user without READ_REPORTS cannot open the consolidated intervention report."""
    headers = make_headers(
        get_access(client, roles=[Role.DISPENSING_MANAGER.value])
    )

    response = client.post(INTERVENTION_URL, json={"year": 2026}, headers=headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_intervention_report_requires_year(client, analyst_headers):
    """The request body must carry a year [400 BAD REQUEST]."""
    response = client.post(
        INTERVENTION_URL, json={"segment": ["Adulto"]}, headers=analyst_headers
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_intervention_report_accepts_full_filter_set(client, analyst_headers):
    """A valid request with every optional filter is accepted [200 OK]."""
    payload = {
        "year": 2026,
        "department": ["UTI"],
        "segment": ["Adulto"],
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "status": ["a", "n"],
        "responsible": ["Fulano Beltrano"],
        "prescriber": ["Ciclano de Tal"],
        "insurance": ["Convênio Teste"],
        "reason": ["Alergias"],
    }

    response = client.post(INTERVENTION_URL, json=payload, headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["status"] == "success"


@pytest.mark.parametrize("url", [PATIENT_DAY_URL, PRESCRIPTION_URL])
def test_patient_day_and_prescription_permission_denied(client, url):
    """A user without READ_REPORTS cannot open the patient-day or prescription report."""
    headers = make_headers(
        get_access(client, roles=[Role.DISPENSING_MANAGER.value])
    )

    response = client.post(url, json={"year": 2026}, headers=headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.parametrize("url", [PATIENT_DAY_URL, PRESCRIPTION_URL])
def test_patient_day_and_prescription_require_year(client, analyst_headers, url):
    """The request body must carry a year [400 BAD REQUEST]."""
    response = client.post(url, json={"segment": ["Adulto"]}, headers=analyst_headers)

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.parametrize("url", [PATIENT_DAY_URL, PRESCRIPTION_URL])
def test_patient_day_and_prescription_reject_invalid_dates(
    client, analyst_headers, url
):
    """A date that is not an ISO date is refused by the request model [400 BAD REQUEST]."""
    response = client.post(
        url,
        json={"year": 2026, "start_date": "not-a-date"},
        headers=analyst_headers,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.parametrize("url", [PATIENT_DAY_URL, PRESCRIPTION_URL])
def test_patient_day_and_prescription_accept_year_only(client, viewer_headers, url):
    """READ_REPORTS (VIEWER) is enough and the year alone is a valid filter [200 OK]."""
    response = client.post(url, json={"year": 2026}, headers=viewer_headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["status"] == "success"


def test_patient_day_report_accepts_full_filter_set(client, analyst_headers):
    """A valid request with every optional filter is accepted [200 OK]."""
    payload = {
        "year": 2026,
        "id_department": [1, 2],
        "segment": ["Adulto"],
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "global_score_start": 0,
        "global_score_end": 10,
        "weekdays_only": True,
    }

    response = client.post(PATIENT_DAY_URL, json=payload, headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["status"] == "success"


def test_prescription_report_accepts_full_filter_set(client, analyst_headers):
    """A valid request with every optional filter is accepted [200 OK]."""
    payload = {
        "year": 2026,
        "id_department": [1, 2],
        "segment": ["Adulto"],
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "global_score_start": 0,
        "global_score_end": 10,
        "weekdays_only": False,
        "consider_empty_prescriptions": True,
        "remove_prescription_at_discharge_date": "S",
    }

    response = client.post(PRESCRIPTION_URL, json=payload, headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["status"] == "success"
