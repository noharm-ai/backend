"""Tests: infection control writes keep the user's segments, as the screening
does (data_authorization_service.has_segment_authorization).

The demo schema runs with AUTHORIZATION_SEGMENT on and the demo user is
authorized on segments 1 and 2 only (public.usuario_autorizacao). A review is
checked on the segment of the prescription-day the record points at, a manual
follow on the segment of the latest prescription; the interventions a review
records, on the segment of their drug (test_review_intervention.py).
"""

from sqlalchemy import text

from tests.conftest import session, session_commit
from tests.integration.infection_control.helpers import (
    ANTIMICROBIAL_DRUG,
    _day,
    _evaluations,
    _prescribe,
    _prescribe_today,
    _record,
    _review,
)
from utils import status

# no user_autorizacao row of the demo user names it
UNAUTHORIZED_SEGMENT = 99


def _move_prescriptions(admission_number, id_segment):
    """Move the admission's prescriptions (and prescription-days) to another
    segment. An UPDATE, since the insert trigger sets the segment from the
    department."""
    session.execute(
        text(
            "UPDATE demo.prescricao SET idsegmento = :segment "
            "WHERE nratendimento = :admission"
        ),
        {"segment": id_segment, "admission": admission_number},
    )
    session_commit()


def _reviews(admission_number):
    return session.execute(
        text("SELECT * FROM demo.ci_revisao WHERE nratendimento = :admission"),
        {"admission": admission_number},
    ).all()


def test_review_refused_out_of_the_segment(
    client, infection_controller_headers, infection_control, admission
):
    """401 to review a patient whose latest prescription-day is in a segment
    the user is not authorized on; nothing is written"""
    _prescribe_today(admission)
    _move_prescriptions(admission, UNAUTHORIZED_SEGMENT)

    response = _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.get_json()["code"] == "errors.businessRules"
    assert "segmento" in response.get_json()["message"]
    assert _reviews(admission) == []
    assert _evaluations(admission) == []


def test_review_accepted_in_the_segment(
    client, infection_controller_headers, infection_control, admission
):
    """The same review in an authorized segment is saved"""
    _prescribe_today(admission)

    response = _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
    )

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    assert len(_reviews(admission)) == 1


def test_follow_refused_out_of_the_segment(
    client, infection_controller_headers, infection_control, admission
):
    """401 to follow by hand a patient whose latest prescription is in a
    segment the user is not authorized on, even before prescalc saw it"""
    _prescribe(admission, _day(-1), _day(1))
    _move_prescriptions(admission, UNAUTHORIZED_SEGMENT)

    response = client.post(
        f"/infection-control/admission/{admission}/follow",
        headers=infection_controller_headers,
    )
    session_commit()

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "segmento" in response.get_json()["message"]
    assert _record(admission) is None
