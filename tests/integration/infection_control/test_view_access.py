"""Tests: the roles that view the infection control data without reviewing

PRESCRIPTION_ANALYST and CONFIG_MANAGER have READ_INFECTION_CONTROL: they open
the worklist and an admission's page (state, timeline, cultures, exams,
antimicrobial search, review reasons) in a schema with the feature on, and
save nothing. CONFIG_MANAGER has no READ_PRESCRIPTION, so the page's reads that
belong to it (cultures, exams) are open to it only with the feature on.
"""

import pytest

from tests.integration.infection_control.helpers import (
    ANTIMICROBIAL_DRUG,
    PENDING,
    _prescribe_today,
    _review,
)
from utils import status

VIEWING_ROLES = ["analyst_headers", "config_manager_headers"]


def _cultures_url(admission_number):
    return f"/infection-control/admission/{admission_number}/cultures"


def _exams_url(admission_number):
    return f"/exams/{admission_number}?idSegment=1"


@pytest.mark.parametrize("role", VIEWING_ROLES)
def test_views_the_worklist(request, client, role, infection_control, admission):
    """The followed admission is listed"""
    headers = request.getfixturevalue(role)
    _prescribe_today(admission)

    response = client.post(
        "/infection-control/admissions",
        json={"status": [PENDING], "admissionNumbers": [admission]},
        headers=headers,
    )

    assert response.status_code == status.HTTP_200_OK
    assert [
        a["admissionNumber"] for a in response.get_json()["data"]["admissions"]
    ] == [admission]


@pytest.mark.parametrize("role", VIEWING_ROLES)
def test_views_the_admission_page(request, client, role, infection_control, admission):
    """The page's reads all answer"""
    headers = request.getfixturevalue(role)
    _prescribe_today(admission)

    for url in (
        f"/infection-control/antimicrobial-timeline/{admission}",
        f"/infection-control/admission/{admission}",
        _cultures_url(admission),
        _exams_url(admission),
        "/infection-control/antimicrobials?term=AMPI",
        "/infection-control/clinical-note-types",
        "/infection-control/exam-triggers",
        "/intervention/reasons",
    ):
        response = client.get(url, headers=headers)
        assert response.status_code == status.HTTP_200_OK, url

    state = client.get(f"/infection-control/admission/{admission}", headers=headers)
    assert state.get_json()["data"]["enabled"] is True


@pytest.mark.parametrize("role", VIEWING_ROLES)
def test_saves_nothing(request, client, role, infection_control, admission):
    """Neither the review, the manual follow nor the exam trigger rules"""
    headers = request.getfixturevalue(role)
    _prescribe_today(admission)

    review = _review(client, headers, admission, evaluations=[ANTIMICROBIAL_DRUG])
    assert review.status_code == status.HTTP_401_UNAUTHORIZED

    for method, url, payload in (
        ("post", f"/infection-control/admission/{admission}/follow", {}),
        ("put", "/infection-control/exam-triggers", {"rules": []}),
    ):
        response = getattr(client, method)(url, json=payload, headers=headers)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED, url


def test_config_manager_needs_the_feature(client, config_manager_headers, admission):
    """Without the feature, READ_INFECTION_CONTROL alone opens neither the
    cultures nor the exams"""
    for url in (_cultures_url(admission), _exams_url(admission)):
        response = client.get(url, headers=config_manager_headers)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, url

    state = client.get(
        f"/infection-control/admission/{admission}", headers=config_manager_headers
    )
    assert state.status_code == status.HTTP_200_OK
    assert state.get_json()["data"]["enabled"] is False


def test_analyst_reads_cultures_and_exams_without_the_feature(
    client, analyst_headers, admission
):
    """READ_PRESCRIPTION keeps opening them, feature or not"""
    for url in (_cultures_url(admission), _exams_url(admission)):
        response = client.get(url, headers=analyst_headers)
        assert response.status_code == status.HTTP_200_OK, url
