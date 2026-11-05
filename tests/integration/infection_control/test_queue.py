"""Tests: infection control follow-up, the light job's queue (ci_fila)

Prescalc queues every followed admission it sees, with or without an
antimicrobial in the prescription-day; the job entry dequeues the admission it
applied the rule to, unless it was queued again while the rule ran or the
record was held by a writer."""

import json
from datetime import datetime, timedelta

from sqlalchemy import text

from models.enums import InfectionControlQueueReasonEnum
from models.main import db, dbSession
from repository.infection_control import infection_control_repository
from services.infection_control import infection_control_job_service
from static import infection_control_sync
from tests.conftest import session, session_commit
from tests.integration.infection_control.helpers import (
    CLOSED,
    OTHER_DRUG,
    _discharge,
    _hold_record,
    _prescalc,
    _prescribe_today,
    _queued,
    _record,
    _run_job,
    _suspend,
)
from utils.static_context import static_user_context

PRESCALC = InfectionControlQueueReasonEnum.PRESCALC.value


def _unqueue(admission_number):
    """Empty the admission's queue row, as a job run would"""
    session.execute(
        text("DELETE FROM demo.ci_fila WHERE nratendimento = :admission"),
        {"admission": admission_number},
    )
    session_commit()


def _queue(admission_number, reasons, queued_at):
    """Queue the admission by hand"""
    session.execute(
        text(
            "INSERT INTO demo.ci_fila (nratendimento, dt_fila, motivos, created_at) "
            "VALUES (:admission, :queued_at, :reasons, :queued_at)"
        ),
        {"admission": admission_number, "reasons": reasons, "queued_at": queued_at},
    )
    session_commit()


def _sync(admission_number):
    """Call the job entry for one admission, as backend-private does"""
    response = json.loads(
        infection_control_sync(
            {"schema": "demo", "admission_number": admission_number}, None
        )
    )
    session_commit()

    assert response["status"] == "success", response
    return response["data"]


def test_prescalc_queues_admission_it_follows(infection_control, admission):
    """An admission prescalc starts following is queued for the job to open
    the reasons of its drugs"""
    _prescribe_today(admission, job=False)

    queued = _queued(admission)
    assert queued is not None
    assert queued["motivos"] == [PRESCALC]


def test_prescalc_queues_followed_admission_without_antimicrobial(
    infection_control, admission
):
    """A followed admission is queued even when its prescription-day has no
    antimicrobial: the drug may have been dropped"""
    _prescribe_today(admission)
    _unqueue(admission)

    _prescribe_today(admission, drugs=(OTHER_DRUG,), job=False)

    assert _queued(admission) is not None


def test_prescalc_follows_even_when_queueing_fails(
    infection_control, admission, monkeypatch
):
    """A failure to queue (e.g. a schema without ci_fila yet) does not undo the
    follow, which the full job can't make up for"""

    def fail(*args, **kwargs):
        raise RuntimeError("queue failure")

    monkeypatch.setattr(
        "repository.infection_control.infection_control_repository.enqueue_followed",
        fail,
    )

    _prescribe_today(admission, job=False)

    assert _record(admission) is not None
    assert _queued(admission) is None


def test_prescalc_without_feature_queues_nothing(admission):
    """A schema without the INFECTION_CONTROL feature queues nothing"""
    _prescribe_today(admission, job=False)

    assert _queued(admission) is None


def test_prescalc_does_not_queue_admission_not_followed(infection_control, admission):
    """An admission without a record and without antimicrobials is not queued"""
    _prescribe_today(admission, drugs=(OTHER_DRUG,), job=False)

    assert _queued(admission) is None


def test_prescalc_does_not_queue_closed_admission(infection_control, admission):
    """A closed admission is not followed: a prescription-day without
    antimicrobials leaves it out of the queue"""
    _suspend(_prescribe_today(admission))
    _run_job(admission)
    assert _record(admission)["tp_status"] == CLOSED
    _unqueue(admission)

    _prescribe_today(admission, drugs=(OTHER_DRUG,), job=False)

    assert _queued(admission) is None


def test_prescalc_queues_followed_discharged_admission(infection_control, admission):
    """A followed admission recalculated after discharge is queued, so the job
    closes it"""
    id_prescription = _prescribe_today(admission)
    _unqueue(admission)
    _discharge(admission)

    _prescalc(id_prescription)
    assert _queued(admission) is not None

    assert _sync(admission) == "changed"
    assert _record(admission)["tp_status"] == CLOSED
    assert _queued(admission) is None


def test_queueing_again_keeps_one_row(infection_control, admission):
    """Queued again, the admission keeps one row: the last time moves, the
    first one and the reasons stay"""
    _prescribe_today(admission, job=False)
    first = _queued(admission)

    _prescribe_today(admission, job=False)
    again = _queued(admission)

    assert again["dt_fila"] > first["dt_fila"]
    assert again["created_at"] == first["created_at"]
    assert again["motivos"] == [PRESCALC]


def test_queueing_adds_its_reason(infection_control, admission):
    """A reason not queued yet is added to the ones already there"""
    _prescribe_today(admission)
    _unqueue(admission)
    _queue(admission, ["other"], datetime.now() - timedelta(minutes=5))

    _prescribe_today(admission, job=False)

    assert _queued(admission)["motivos"] == ["other", PRESCALC]


def test_job_dequeues_admission(infection_control, admission):
    """The job entry dequeues the admission it applied the rule to"""
    _prescribe_today(admission, job=False)

    assert _sync(admission) == "processed"

    assert _queued(admission) is None


def test_job_keeps_admission_held_by_a_writer_queued(infection_control, admission):
    """A record locked by a review save is skipped and stays queued for the
    next run"""
    _prescribe_today(admission, job=False)

    _hold_record(admission)
    try:
        with static_user_context("demo") as user_context:
            outcome = infection_control_job_service.sync_followed_admission(
                schema="demo",
                admission_number=admission,
                user_context=user_context,
                lock_timeout_ms=100,
            )
            db.session.commit()
            db.session.remove()
    finally:
        session_commit()

    assert outcome == "skipped"
    assert _queued(admission) is not None


def test_job_dequeues_admission_not_followed(infection_control, admission):
    """An admission with nothing to follow is dequeued, not retried forever"""
    _queue(admission, [PRESCALC], datetime.now())

    assert _sync(admission) == "skipped"

    assert _record(admission) is None
    assert _queued(admission) is None


def test_dequeue_keeps_admission_queued_again(infection_control, admission):
    """Queued again after the job read it, the admission stays: that change
    may have come after the rule read the prescriptions"""
    _prescribe_today(admission, job=False)
    read_at = _queued(admission)["dt_fila"]
    _prescribe_today(admission, job=False)

    with static_user_context("demo"):
        dbSession.setSchema("demo")
        removed = infection_control_repository.dequeue(
            admission_number=admission, queued_at=read_at
        )
        db.session.commit()
        db.session.remove()
    session_commit()

    assert removed is False
    assert _queued(admission) is not None
