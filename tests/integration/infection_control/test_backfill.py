"""Tests: infection control follow-up, the backfill of admissions already on antimicrobials"""

from models.enums import InfectionControlOriginEnum
from tests.conftest import session_commit
from tests.integration.infection_control.helpers import (
    CPOE_SEGMENT,
    PENDING,
    _day,
    _prescribe,
    _record,
)
from utils import status


def test_backfill_requires_integration_utils(
    client, analyst_headers, infection_control
):
    """401 without INTEGRATION_UTILS"""
    response = client.post(
        "/infection-control/backfill", json={}, headers=analyst_headers
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_backfill_follows_admission_on_antimicrobial(
    client, admin_utils_headers, infection_control, admission
):
    """Admissions already on antimicrobials are followed without prescalc"""
    _prescribe(admission, _day(-1), _day(1))

    response = client.post(
        "/infection-control/backfill",
        json={"after": admission - 1, "limit": 200},
        headers=admin_utils_headers,
    )
    session_commit()

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    assert response.get_json()["data"]["created"] >= 1
    record = _record(admission)
    assert record["tp_origem"] == InfectionControlOriginEnum.BACKFILL.value
    assert record["tp_status"] == PENDING


def test_backfill_follows_open_ended_cpoe_order(
    client, admin_utils_headers, infection_control, cpoe_antimicrobial, admission
):
    """A CPOE order started days ago and still open is followed"""
    _prescribe(admission, _day(-5), None, id_segment=CPOE_SEGMENT)

    response = client.post(
        "/infection-control/backfill",
        json={"after": admission - 1, "limit": 200},
        headers=admin_utils_headers,
    )
    session_commit()

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    record = _record(admission)
    assert record is not None
    assert record["tp_origem"] == InfectionControlOriginEnum.BACKFILL.value
