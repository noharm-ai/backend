"""Tests: infection control follow-up, prescalc follows admissions on antimicrobials and never breaks the
prescription-day"""

import json
from datetime import datetime, timedelta

from sqlalchemy import text

from models.enums import InfectionControlOriginEnum
from static import atendcalc, prescalc
from tests.conftest import session, session_commit
from tests.integration.infection_control.helpers import (
    ANTIMICROBIAL_DRUG,
    CLOSED,
    CPOE_SEGMENT,
    NEVER_REVIEWED,
    NO_EVALUATION,
    OTHER_DRUG,
    PENDING,
    REVISED,
    _day,
    _discharge,
    _hold_record,
    _open_pendings,
    _prescalc,
    _prescribe,
    _prescribe_today,
    _record,
    _review,
    _run_job,
    _suspend,
)


def test_prescalc_without_feature_follows_nothing(admission):
    """A schema without the INFECTION_CONTROL feature is not followed"""
    _prescribe_today(admission, job=False)

    assert _record(admission) is None


def test_prescalc_without_antimicrobial_follows_nothing(infection_control, admission):
    """A prescription-day without antimicrobials does not follow the admission"""
    _prescribe_today(admission, drugs=(OTHER_DRUG,), job=False)

    assert _record(admission) is None


def test_prescalc_follows_admission(infection_control, admission):
    """An antimicrobial makes the admission pending and never reviewed; the
    reasons of its drugs are left to the job"""
    id_prescription = _prescribe_today(admission, job=False)

    record = _record(admission)
    assert record["tp_status"] == PENDING
    assert record["tp_origem"] == InfectionControlOriginEnum.PRESCALC.value
    # prescalc runs as the static (integration) user
    assert record["created_by"] == 0

    pendings = _open_pendings(admission)
    assert [p["tp_pendencia"] for p in pendings] == [NEVER_REVIEWED]
    assert pendings[0]["fkprescricao"] == id_prescription
    assert pendings[0]["tp_origem"] == InfectionControlOriginEnum.PRESCALC.value


def test_daily_prescriptions_keep_a_single_reason(infection_control, admission):
    """Prescalc on consecutive daily prescriptions opens 'never reviewed' once"""
    _prescalc(_prescribe(admission, _day(-1), _day(0)))
    _prescalc(_prescribe(admission, _day(0), _day(1)))

    pendings = _open_pendings(admission)
    assert [p["tp_pendencia"] for p in pendings] == [NEVER_REVIEWED]


def test_prescalc_leaves_reviewed_admission_alone(
    client, infection_controller_headers, infection_control, admission
):
    """A followed admission is the job's: prescalc doesn't reopen 'never
    reviewed' after a review"""
    _prescribe_today(admission)
    _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
    )

    _prescribe_today(admission, job=False)

    assert _record(admission)["tp_status"] == REVISED
    assert _open_pendings(admission) == []


def test_atendcalc_follows_cpoe_admission(
    infection_control, cpoe_antimicrobial, admission
):
    """The CPOE path (atendcalc) follows the admission too"""
    _prescribe(admission, _day(-1), _day(2), id_segment=CPOE_SEGMENT)

    atendcalc({"schema": "demo", "admission_number": admission}, None)
    session_commit()

    record = _record(admission)
    assert record is not None
    assert record["tp_status"] == PENDING
    assert [p["tp_pendencia"] for p in _open_pendings(admission)] == [NEVER_REVIEWED]


def test_prescalc_reopens_closed_admission(infection_control, admission):
    """An antimicrobial restarted on a closed admission makes it pending again"""
    _suspend(_prescribe_today(admission))
    _run_job(admission)
    assert _record(admission)["tp_status"] == CLOSED

    _prescribe_today(admission, job=False)

    record = _record(admission)
    assert record["tp_status"] == PENDING
    # never reviewed: the reason is open again
    assert [p["tp_pendencia"] for p in _open_pendings(admission)] == [NEVER_REVIEWED]


def test_prescalc_reopens_reviewed_admission_for_the_job(
    client, infection_controller_headers, infection_control, admission
):
    """A reviewed admission reopened by prescalc waits for the job to open the
    reasons of its drugs"""
    id_prescription = _prescribe_today(admission)
    _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
    )
    _suspend(id_prescription)
    _run_job(admission)
    assert _record(admission)["tp_status"] == CLOSED

    _prescribe_today(admission, job=False)

    assert _record(admission)["tp_status"] == PENDING
    assert _open_pendings(admission) == []

    _run_job(admission)

    assert [
        (p["tp_pendencia"], p["fkmedicamento"]) for p in _open_pendings(admission)
    ] == [(NO_EVALUATION, ANTIMICROBIAL_DRUG)]


def test_prescalc_does_not_reopen_discharged_admission(
    client, infection_controller_headers, infection_control, admission
):
    """Recalculating a discharged patient's prescription keeps the record closed"""
    id_prescription = _prescribe_today(admission)
    _review(client, infection_controller_headers, admission)
    _discharge(admission)
    _run_job(admission)
    assert _record(admission)["tp_status"] == CLOSED

    _prescalc(id_prescription)

    assert _record(admission)["tp_status"] == CLOSED
    assert _open_pendings(admission) == []


def test_prescalc_does_not_follow_discharged_admission(infection_control, admission):
    """A discharged patient is not followed"""
    _discharge(admission)

    _prescribe_today(admission, job=False)

    assert _record(admission) is None


def _patient_day(admission_number):
    return session.execute(
        text(
            "SELECT fkprescricao FROM demo.prescricao "
            "WHERE nratendimento = :admission AND agregada = true"
        ),
        {"admission": admission_number},
    ).first()


def test_prescalc_survives_hook_failure(infection_control, admission, monkeypatch):
    """A failure in the infection control step does not stop the prescription-day"""

    def fail(*args, **kwargs):
        raise RuntimeError("infection control failure")

    monkeypatch.setattr(
        "repository.infection_control.infection_control_repository.create_admission",
        fail,
    )

    _prescribe_today(admission, job=False)

    assert _patient_day(admission) is not None
    assert _record(admission) is None


def test_prescalc_does_not_wait_for_a_review(
    infection_control, admission, second_antimicrobial
):
    """A review holding a followed record doesn't make prescalc wait: the
    record is the job's"""
    _prescribe_today(admission)

    id_prescription = _prescribe(
        admission, _day(-1), _day(1), drugs=(ANTIMICROBIAL_DRUG, second_antimicrobial)
    )

    # creating the prescription above commits the test session, so the lock is
    # taken only now
    _hold_record(admission)
    started = datetime.now()
    try:
        response = json.loads(
            prescalc(
                {"schema": "demo", "id_prescription": id_prescription, "force": True},
                None,
            )
        )
    finally:
        session_commit()

    assert response["status"] == "success", response
    assert datetime.now() - started < timedelta(seconds=2)
    assert _record(admission)["tp_status"] == PENDING
