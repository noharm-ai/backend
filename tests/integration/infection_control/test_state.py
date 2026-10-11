"""Tests: infection control follow-up, the admission state and the worklist"""

from tests.integration.infection_control.helpers import (
    NEVER_REVIEWED,
    NO_EVALUATION,
    PATIENT_ID,
    PENDING,
    _prescribe_today,
)
from utils import status


def test_state_without_feature(client, analyst_headers, admission):
    """The page learns the feature is off"""
    response = client.get(
        f"/infection-control/admission/{admission}", headers=analyst_headers
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["enabled"] is False


def test_state_of_followed_admission(
    client, analyst_headers, infection_control, admission
):
    """Status, open reasons and the courses of a followed admission"""
    _prescribe_today(admission)

    response = client.get(
        f"/infection-control/admission/{admission}", headers=analyst_headers
    )

    data = response.get_json()["data"]
    assert data["followed"] is True
    assert data["status"] == PENDING
    assert [p["type"] for p in data["pendings"]] == [NEVER_REVIEWED, NO_EVALUATION]
    assert data["courses"][0]["evaluation"] is None


def test_worklist_requires_permission(
    client, analyst_headers, infection_control, admission
):
    """401 without READ_INFECTION_CONTROL, even with READ_PRESCRIPTION"""
    _prescribe_today(admission)

    response = client.post(
        "/infection-control/admissions",
        json={"status": [PENDING], "limit": 500},
        headers=analyst_headers,
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_worklist_lists_pending_admission(
    client, infection_controller_headers, infection_control, admission
):
    """The worklist brings the admission with its open reasons"""
    _prescribe_today(admission)

    response = client.post(
        "/infection-control/admissions",
        json={"status": [PENDING], "limit": 500},
        headers=infection_controller_headers,
    )

    assert response.status_code == status.HTTP_200_OK
    rows = [
        a
        for a in response.get_json()["data"]["admissions"]
        if a["admissionNumber"] == admission
    ]
    assert len(rows) == 1
    assert rows[0]["idPatient"] == str(PATIENT_ID)
    assert [p["type"] for p in rows[0]["pendings"]] == [NEVER_REVIEWED, NO_EVALUATION]
