"""Tests: infection control follow-up, the summary the report reads
(ci_atendimento.resumo_acompanhamento), kept by the rule on every run and
written only when it changes"""

from datetime import datetime, timedelta

from sqlalchemy import inspect, text

from models.enums import InfectionControlOriginEnum, InfectionControlStatusEnum
from models.infection_control import InfectionControlAdmission
from models.main import db, dbSession
from services.infection_control import (
    infection_control_status_service,
    infection_control_summary_service,
)
from tests.conftest import session, session_commit
from tests.integration.infection_control.helpers import (
    ANTIMICROBIAL_DRUG,
    CLOSED,
    CPOE_SEGMENT,
    PENDING,
    _day,
    _discharge,
    _evaluations,
    _prescribe,
    _prescribe_today,
    _record,
    _review,
    _suspend,
)
from utils import status
from utils.static_context import static_user_context


def _sync(admission_number, now=None):
    """Apply the rule to the admission at `now`, as the scheduled job does"""
    with static_user_context("demo"):
        dbSession.setSchema("demo")
        infection_control_status_service.sync_admission(
            admission_number=admission_number,
            origin=InfectionControlOriginEnum.JOB,
            user_id=0,
            now=now,
        )
        db.session.commit()
        db.session.remove()
    session_commit()


def _summary(admission_number):
    record = _record(admission_number)
    return record["resumo_acompanhamento"] if record else None


def test_summary_written_on_first_run(infection_control, admission):
    """The rule keeps the running course and the department of each day"""
    _prescribe_today(admission)

    summary = _summary(admission)

    assert summary["v"] == infection_control_summary_service.SUMMARY_VERSION
    assert summary["status"] == PENDING
    [course] = summary["courses"]
    assert course["n"] == 1
    assert course["idDrug"] == ANTIMICROBIAL_DRUG
    assert course["ongoing"] is True
    assert course["end"] is None
    assert course["endedBy"] is None
    assert course["coveredUntil"] == datetime.now().date().isoformat()
    assert course["start"] == _day(-1).isoformat()
    # the course started yesterday at 08:00: D2 begins only at 08:00 today
    assert course["treatmentDays"] == (2 if datetime.now() >= _day(0) else 1)
    assert [r["dose"] for r in course["regimens"]] == [2.0]
    assert summary["days"]
    assert summary["days"][-1]["idDepartment"] is not None
    assert "culture" not in summary


def test_summary_not_rewritten_without_changes(infection_control, admission):
    """Another run that sees the same courses leaves the summary as it was"""
    _prescribe_today(admission)
    first = _summary(admission)

    _sync(admission, now=datetime.now() + timedelta(minutes=30))

    assert _summary(admission)["savedAt"] == first["savedAt"]


def test_culture_facts_of_an_older_summary_are_dropped(infection_control, admission):
    """A summary saved while the job still refreshed the cultures loses them
    on the next run: the report no longer reads them"""
    _prescribe_today(admission)
    session.execute(
        text(
            "UPDATE demo.ci_atendimento "
            "SET resumo_acompanhamento = resumo_acompanhamento "
            "|| CAST(:culture AS jsonb) "
            "WHERE nratendimento = :admission"
        ),
        {"admission": admission, "culture": '{"culture": {"collected": 1}}'},
    )
    session_commit()
    assert "culture" in _summary(admission)

    _sync(admission, now=datetime.now() + timedelta(minutes=30))

    assert "culture" not in _summary(admission)


def test_running_cpoe_course_not_rewritten_every_hour(
    infection_control, cpoe_antimicrobial, admission
):
    """An open-ended order runs until now on every run: the summary keeps it
    at day precision, so the next hourly run changes nothing"""
    _prescribe(admission, _day(-3), None, id_segment=CPOE_SEGMENT)
    now = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
    _sync(admission, now=now)
    first = _summary(admission)
    assert first["courses"][0]["ongoing"] is True
    assert first["courses"][0]["cpoe"] is True

    _sync(admission, now=now + timedelta(hours=1))

    assert _summary(admission)["savedAt"] == first["savedAt"]


def test_closing_fills_the_end_of_the_course(infection_control, admission):
    """A suspended drug ends its course and closes the summary"""
    _suspend(_prescribe_today(admission))

    _sync(admission)

    summary = _summary(admission)
    assert summary["status"] == CLOSED
    [course] = summary["courses"]
    assert course["ongoing"] is False
    assert course["endedBy"] == infection_control_summary_service.ENDED_SUSPENDED
    assert course["end"] is not None
    assert course["coveredUntil"] == course["end"][:10]


def test_discharge_ends_the_course(infection_control, admission):
    """A course running at discharge ends at the discharge"""
    _prescribe_today(admission)
    _discharge(admission)

    _sync(admission)

    [course] = _summary(admission)["courses"]
    assert course["endedBy"] == infection_control_summary_service.ENDED_DISCHARGE
    assert course["end"] <= datetime.now().isoformat()


def test_summary_lists_the_evaluations_of_each_course(
    client, infection_controller_headers, infection_control, admission
):
    """A saved review runs the rule: the summary names the evaluation of the
    course"""
    _prescribe_today(admission)

    response = _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
    )

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    [evaluation] = _evaluations(admission)
    summary = _summary(admission)
    assert summary["courses"][0]["idEvaluations"] == [evaluation["idci_avaliacao_atm"]]
    assert summary["status"] == InfectionControlStatusEnum.REVISED.value


def test_reopened_admission_rewrites_the_summary(infection_control, admission):
    """A closed admission whose antimicrobial restarts is followed again, and
    the summary follows it"""
    _suspend(_prescribe_today(admission))
    _sync(admission)
    assert _summary(admission)["status"] == CLOSED

    _prescribe_today(admission)

    summary = _summary(admission)
    assert summary["status"] == PENDING
    assert summary["courses"][-1]["ongoing"] is True


def test_summary_matches_the_timeline(
    client, infection_controller_headers, infection_control, admission
):
    """The courses of the summary are the timeline's"""
    _prescribe(admission, _day(-4), _day(-3))
    _prescribe_today(admission)

    response = client.get(
        f"/infection-control/antimicrobial-timeline/{admission}",
        headers=infection_controller_headers,
    )

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    timeline = response.get_json()["data"]["courses"]
    summary = _summary(admission)["courses"]
    assert [c["start"] for c in summary] == [c["start"] for c in timeline]
    assert [c["idDrug"] for c in summary] == [c["idDrug"] for c in timeline]
    assert [len(c["gaps"]) for c in summary] == [len(c["gaps"]) for c in timeline]
    assert [[r["route"] for r in c["regimens"]] for c in summary] == [
        [r["route"] for r in c["regimens"]] for c in timeline
    ]


def test_summary_is_not_loaded_with_the_record(infection_control, admission):
    """The worklist loads records without the summary (deferred column)"""
    _prescribe_today(admission)

    with static_user_context("demo"):
        dbSession.setSchema("demo")
        record = (
            db.session.query(InfectionControlAdmission)
            .filter(InfectionControlAdmission.admission_number == admission)
            .first()
        )
        assert "summary" not in inspect(record).dict
        db.session.remove()


def test_backfill_summary_requires_integration_utils(
    client, analyst_headers, infection_control
):
    """401 without INTEGRATION_UTILS"""
    response = client.post(
        "/infection-control/backfill-summary", json={}, headers=analyst_headers
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_backfill_summary_fills_closed_admission(
    client, admin_utils_headers, infection_control, admission
):
    """A closed admission without a summary (closed before it existed) gets
    one from its courses"""
    _suspend(_prescribe_today(admission))
    _sync(admission)
    session.execute(
        text(
            "UPDATE demo.ci_atendimento SET resumo_acompanhamento = NULL "
            "WHERE nratendimento = :admission"
        ),
        {"admission": admission},
    )
    session_commit()

    response = client.post(
        "/infection-control/backfill-summary",
        json={"after": admission - 1, "limit": 200},
        headers=admin_utils_headers,
    )
    session_commit()

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    assert response.get_json()["data"]["filled"] >= 1
    summary = _summary(admission)
    assert summary["status"] == CLOSED
    assert summary["courses"][0]["ongoing"] is False
    assert _record(admission)["tp_status"] == CLOSED
