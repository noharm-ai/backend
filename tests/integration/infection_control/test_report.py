"""Tests: POST /reports/consolidated/infection-control

The infection control report is read by the private backend lambda (short
circuited under ENV=test) from the files long-running-tasks builds. What this
backend owns is the gate in front of it: the READ_INFECTION_CONTROL permission
(not READ_REPORTS, unlike the other consolidated reports), the INFECTION_CONTROL
feature of the schema and the request validation.
"""

import pytest

from security.role import Role
from tests.conftest import get_access, make_headers
from utils import status

URL = "/reports/consolidated/infection-control"

FULL_FILTER_SET = {
    "year": 2026,
    "start_date": "2026-01-01",
    "end_date": "2026-01-31",
    "id_department": [1, 2],
    "segment": ["Adulto"],
    "substance": [1, 2],
    "aware_level": [1, 2],
    "reviewer": [1],
    "treatment_type": [1, 2],
    "infection_focus": [3, 4],
    "day": "2026-01-15",
    "admissions_of": 1,
    "courses_of": 123,
}


def _headers(client, role: Role):
    """Headers of the demo user acting with a single role"""
    return make_headers(get_access(client, roles=[role.value]))


def test_report_refused_without_the_feature(client, infection_controller_headers):
    """The schema without INFECTION_CONTROL has no report [400 BAD REQUEST]."""
    response = client.post(URL, json={"year": 2026}, headers=infection_controller_headers)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["message"] == "Controle de infecção não habilitado"


def test_report_with_the_feature(
    client, infection_control, infection_controller_headers
):
    """With the feature on, the year alone is a valid request [200 OK]."""
    response = client.post(URL, json={"year": 2026}, headers=infection_controller_headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["status"] == "success"


def test_report_accepts_full_filter_set(
    client, infection_control, infection_controller_headers
):
    """Every optional filter (period, day view and drill-downs) is accepted [200 OK]."""
    response = client.post(
        URL, json=FULL_FILTER_SET, headers=infection_controller_headers
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["status"] == "success"


@pytest.mark.parametrize(
    "role",
    [Role.INFECTION_CONTROLLER, Role.PRESCRIPTION_ANALYST, Role.CONFIG_MANAGER],
)
def test_report_open_to_infection_control_readers(client, infection_control, role):
    """Every role with READ_INFECTION_CONTROL opens it, CONFIG_MANAGER included,
    though it has no READ_REPORTS [200 OK]."""
    response = client.post(URL, json={"year": 2026}, headers=_headers(client, role))

    assert response.status_code == status.HTTP_200_OK


@pytest.mark.parametrize("role", [Role.VIEWER, Role.RESEARCHER, Role.REGULATOR])
def test_report_refused_to_report_readers_without_infection_control(
    client, infection_control, role
):
    """READ_REPORTS alone is not enough: the report needs READ_INFECTION_CONTROL
    [401 UNAUTHORIZED]."""
    response = client.post(URL, json={"year": 2026}, headers=_headers(client, role))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_report_requires_year(client, infection_control, infection_controller_headers):
    """The request body must carry a year [400 BAD REQUEST]."""
    response = client.post(
        URL, json={"segment": ["Adulto"]}, headers=infection_controller_headers
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_report_rejects_an_invalid_day(
    client, infection_control, infection_controller_headers
):
    """The day of the day view must be an ISO date [400 BAD REQUEST]."""
    response = client.post(
        URL,
        json={"year": 2026, "day": "15/01/2026"},
        headers=infection_controller_headers,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
