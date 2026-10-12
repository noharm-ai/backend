"""Tests: infection control follow-up, the admission state and the worklist"""

from datetime import datetime, timedelta

from sqlalchemy import text

from tests.conftest import session, session_commit
from tests.integration.infection_control.helpers import (
    ADULT_SEGMENT,
    CLOSED,
    CPOE_SEGMENT,
    DEPARTMENT_BY_SEGMENT,
    NEVER_REVIEWED,
    NO_EVALUATION,
    PATIENT_ID,
    PENDING,
    REVISED,
    SCHEDULED_DATE,
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


def _worklist(client, headers, admission, **filters):
    """The worklist narrowed to one admission, plus the given filters"""
    response = client.post(
        "/infection-control/admissions",
        json={"status": [PENDING], "admissionNumbers": [admission], **filters},
        headers=headers,
    )
    assert response.status_code == status.HTTP_200_OK
    return response.get_json()["data"]


def test_worklist_filters_by_department(
    client, infection_controller_headers, infection_control, admission
):
    """The department of the latest prescription narrows the worklist"""
    _prescribe_today(admission)

    def listed(**filters):
        data = _worklist(client, infection_controller_headers, admission, **filters)
        return [a["admissionNumber"] for a in data["admissions"]]

    assert listed(idDepartment=[DEPARTMENT_BY_SEGMENT[ADULT_SEGMENT]]) == [admission]
    assert listed(idDepartment=[DEPARTMENT_BY_SEGMENT[CPOE_SEGMENT]]) == []


def test_worklist_filters_by_pending_type(
    client, infection_controller_headers, infection_control, admission
):
    """Only admissions with an open reason of the chosen types"""
    _prescribe_today(admission)

    def listed(**filters):
        data = _worklist(client, infection_controller_headers, admission, **filters)
        return [a["admissionNumber"] for a in data["admissions"]]

    assert listed(pendingTypes=[NO_EVALUATION]) == [admission]
    assert listed(pendingTypes=[SCHEDULED_DATE, NO_EVALUATION]) == [admission]
    assert listed(pendingTypes=[SCHEDULED_DATE]) == []


def test_worklist_counts_the_matching_admissions(
    client, infection_controller_headers, infection_control, admission
):
    """count is every admission matching the filters and statuses, beyond
    the limit"""
    _prescribe_today(admission)

    def worklist(statuses, limit=500):
        return client.post(
            "/infection-control/admissions",
            json={
                "status": statuses,
                "admissionNumbers": [admission],
                "limit": limit,
            },
            headers=infection_controller_headers,
        ).get_json()["data"]

    assert worklist([PENDING])["count"] == 1
    assert worklist([REVISED, CLOSED])["count"] == 0
    assert worklist([PENDING, REVISED])["count"] == 1

    # a page past the admissions still counts them all
    past = client.post(
        "/infection-control/admissions",
        json={"status": [PENDING], "admissionNumbers": [admission], "offset": 1},
        headers=infection_controller_headers,
    ).get_json()["data"]
    assert past["admissions"] == []
    assert past["count"] == 1


def test_worklist_filters_overdue_review(
    client, infection_controller_headers, infection_control, admission
):
    """Only admissions whose scheduled review date has passed"""
    _prescribe_today(admission)

    def listed():
        data = _worklist(
            client, infection_controller_headers, admission, overdueReview=True
        )
        return [a["admissionNumber"] for a in data["admissions"]]

    # no review scheduled
    assert listed() == []

    for offset, expected in ((1, []), (-1, [admission])):
        session.execute(
            text(
                "UPDATE demo.ci_atendimento SET dt_proxima_revisao = :date "
                "WHERE nratendimento = :admission"
            ),
            {"date": datetime.now() + timedelta(days=offset), "admission": admission},
        )
        session_commit()
        assert listed() == expected
