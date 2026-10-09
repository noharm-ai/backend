"""Tests: infection control follow-up, following an admission by hand"""

from models.enums import InfectionControlOriginEnum
from tests.conftest import session_commit
from tests.integration.infection_control.helpers import (
    NEVER_REVIEWED,
    NO_EVALUATION,
    OTHER_DRUG,
    PENDING,
    _day,
    _discharge,
    _open_pendings,
    _prescribe,
    _prescribe_today,
    _record,
)
from utils import status


def _follow(client, headers, admission_number):
    response = client.post(
        f"/infection-control/admission/{admission_number}/follow", headers=headers
    )
    session_commit()
    return response


def test_follow_requires_permission(
    client, analyst_headers, infection_control, admission
):
    """401 without WRITE_INFECTION_CONTROL"""
    _prescribe(admission, _day(-1), _day(1))

    response = _follow(client, analyst_headers, admission)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert _record(admission) is None


def test_follow_requires_feature(client, infection_controller_headers, admission):
    """400 when the schema does not have the feature"""
    _prescribe(admission, _day(-1), _day(1))

    response = _follow(client, infection_controller_headers, admission)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"


def test_follow_starts_admission_on_antimicrobial(
    client, infection_controller_headers, infection_control, admission
):
    """An admission prescalc missed is followed by hand, pending with the
    reasons of its running drugs"""
    _prescribe(admission, _day(-1), _day(1))

    response = _follow(client, infection_controller_headers, admission)

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    data = response.get_json()["data"]
    assert data["followed"] is True
    assert data["status"] == PENDING
    assert [p["type"] for p in data["pendings"]] == [NEVER_REVIEWED, NO_EVALUATION]
    record = _record(admission)
    assert record["tp_origem"] == InfectionControlOriginEnum.MANUAL.value
    assert record["tp_status"] == PENDING


def test_follow_twice_keeps_a_single_record(
    client, infection_controller_headers, infection_control, admission
):
    """Following an admission already followed only applies the rule"""
    _prescribe_today(admission)

    response = _follow(client, infection_controller_headers, admission)

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    assert _record(admission)["tp_origem"] == InfectionControlOriginEnum.PRESCALC.value
    assert [p["tp_pendencia"] for p in _open_pendings(admission)] == [
        NEVER_REVIEWED,
        NO_EVALUATION,
    ]


def test_follow_rejects_admission_without_antimicrobial(
    client, infection_controller_headers, infection_control, admission
):
    """Nothing to follow without a running antimicrobial"""
    _prescribe(admission, _day(-1), _day(1), drugs=(OTHER_DRUG,))

    response = _follow(client, infection_controller_headers, admission)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"
    assert _record(admission) is None


def test_follow_rejects_discharged_patient(
    client, infection_controller_headers, infection_control, admission
):
    """A discharged patient is not followed, as in prescalc"""
    _prescribe(admission, _day(-1), _day(1))
    _discharge(admission)

    response = _follow(client, infection_controller_headers, admission)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"
    assert _record(admission) is None
