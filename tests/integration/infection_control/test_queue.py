"""Tests: infection control follow-up, the light job's queue (fila_atendimento,
the infection control consumer of admission_queue_service)

Prescalc queues a followed admission only when an antimicrobial it processed
is not among the running courses the rule last saw
(infection_control_repository.queue_condition); the rest waits for the full
run. The job entry
dequeues the admission it applied the rule to, unless it was queued again
while the rule ran or the record was held by a writer. Other consumers' rows
are never touched."""

import json
from datetime import datetime, timedelta

from sqlalchemy import text

from models.enums import AdmissionQueueEnum, AdmissionQueueReasonEnum
from models.main import db, dbSession
from repository import admission_queue_repository
from services.infection_control import infection_control_job_service
from static import infection_control_sync
from tests.conftest import session, session_commit
from tests.integration.infection_control.helpers import (
    ANTIMICROBIAL_DRUG,
    CLOSED,
    INFECTION_CONTROL_QUEUE,
    OTHER_ADULT_DEPARTMENT,
    OTHER_DRUG,
    PENDING,
    _day,
    _discharge,
    _hold_record,
    _last_prescription_day,
    _prescalc,
    _prescribe,
    _prescribe_today,
    _queued,
    _record,
    _run_job,
    _suspend,
)
from utils.static_context import static_user_context

PRESCALC = AdmissionQueueReasonEnum.PRESCALC.value
# a consumer that doesn't exist: its rows must be left alone
OTHER_QUEUE = 99


def _unqueue(admission_number):
    """Empty the admission's queue rows, as a job run would"""
    session.execute(
        text("DELETE FROM demo.fila_atendimento WHERE nratendimento = :admission"),
        {"admission": admission_number},
    )
    session_commit()


def _queue(admission_number, reasons, queued_at, queue=INFECTION_CONTROL_QUEUE):
    """Queue the admission by hand"""
    session.execute(
        text(
            "INSERT INTO demo.fila_atendimento "
            "(tp_fila, nratendimento, dt_fila, motivos, created_at) "
            "VALUES (:queue, :admission, :queued_at, :reasons, :queued_at)"
        ),
        {
            "queue": queue,
            "admission": admission_number,
            "reasons": reasons,
            "queued_at": queued_at,
        },
    )
    session_commit()


def _queue_row(admission_number, queue):
    """The admission's row in a consumer's queue, None when not queued"""
    return session.execute(
        text(
            "SELECT * FROM demo.fila_atendimento "
            "WHERE tp_fila = :queue AND nratendimento = :admission"
        ),
        {"queue": queue, "admission": admission_number},
    ).first()


def _set_running_courses(admission_number, drugs):
    """Make the record hold these drugs as its running courses, as if the rule
    last saw them"""
    session.execute(
        text(
            "UPDATE demo.ci_atendimento SET indicadores = CAST(:features AS jsonb) "
            "WHERE nratendimento = :admission"
        ),
        {
            "features": json.dumps(
                {"courses": [{"idDrug": d} for d in drugs], "nonConforming": False}
            ),
            "admission": admission_number,
        },
    )
    session_commit()


def _prescribe_next_day(admission_number, drugs, id_department=None):
    """A prescription of today (a prescription-day after the daily one's), run
    through prescalc only"""
    id_prescription = _prescribe(
        admission_number, _day(0), _day(2), drugs=drugs, id_department=id_department
    )
    _prescalc(id_prescription)
    return id_prescription


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


def test_prescalc_does_not_queue_followed_admission_without_antimicrobial(
    infection_control, admission
):
    """A prescription without antimicrobials, on a day placing the patient
    where the record already does, changes nothing the rule keeps: a dropped
    drug ends its course with time, which the full run sees"""
    _prescribe_today(admission)
    _unqueue(admission)

    _prescribe_next_day(admission, drugs=(OTHER_DRUG,))

    assert _record(admission)["tp_status"] == PENDING
    assert _queued(admission) is None


def test_prescalc_does_not_queue_running_antimicrobial(infection_control, admission):
    """The daily prescription repeating a running antimicrobial is not queued:
    the rule already follows its course"""
    _prescribe_today(admission)
    _unqueue(admission)

    _prescribe_today(admission, job=False)

    assert _queued(admission) is None


def test_prescalc_queues_antimicrobial_not_running(infection_control, admission):
    """An antimicrobial that is not among the running courses the rule last
    saw (a new drug or a course restarting) is queued, so its reason opens"""
    _prescribe_today(admission)
    _unqueue(admission)
    _set_running_courses(admission, [ANTIMICROBIAL_DRUG + 1000])

    _prescribe_today(admission, job=False)

    assert _queued(admission) is not None


def test_prescalc_queues_admission_it_reopens(infection_control, admission):
    """A record reopened by prescalc was closed with nothing running, so its
    antimicrobials are all new to it: it is queued"""
    _suspend(_prescribe_today(admission))
    _run_job(admission)
    assert _record(admission)["tp_status"] == CLOSED
    _unqueue(admission)

    _prescribe_today(admission, job=False)

    assert _record(admission)["tp_status"] == PENDING
    assert _queued(admission) is not None


def test_prescalc_leaves_new_department_to_full_run(infection_control, admission):
    """A new prescription-day in another department, without a new
    antimicrobial, is not queued: the record points at it after the full run"""
    _prescribe_today(admission)
    _unqueue(admission)

    _prescribe_next_day(
        admission, drugs=(OTHER_DRUG,), id_department=OTHER_ADULT_DEPARTMENT
    )

    assert _queued(admission) is None


def test_prescalc_follows_even_when_queueing_fails(
    infection_control, admission, monkeypatch
):
    """A failure to queue (e.g. a schema without fila_atendimento yet) does not
    undo the follow, which the full job can't make up for, nor the
    prescription-day"""

    def fail(*args, **kwargs):
        raise RuntimeError("queue failure")

    monkeypatch.setattr(
        "repository.admission_queue_repository.enqueue",
        fail,
    )

    _prescribe_today(admission, job=False)

    assert _last_prescription_day(admission) is not None
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


def test_prescalc_leaves_discharge_to_full_run(infection_control, admission):
    """A followed admission recalculated after discharge is not queued: the
    full run closes it, as it does every discharge"""
    id_prescription = _prescribe_today(admission)
    _unqueue(admission)
    _discharge(admission)

    _prescalc(id_prescription)
    assert _queued(admission) is None

    assert _sync(admission) == "changed"
    assert _record(admission)["tp_status"] == CLOSED


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
    _prescribe_today(admission, job=False)
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
        removed = admission_queue_repository.dequeue(
            queue=AdmissionQueueEnum.INFECTION_CONTROL,
            admission_number=admission,
            queued_at=read_at,
        )
        db.session.commit()
        db.session.remove()
    session_commit()

    assert removed is False
    assert _queued(admission) is not None


def test_job_leaves_other_queues_alone(infection_control, admission):
    """Dequeuing the infection control row keeps the admission queued for the
    other consumers, which have not run on it yet"""
    _prescribe_today(admission, job=False)
    _queue(admission, [PRESCALC], datetime.now(), queue=OTHER_QUEUE)

    assert _sync(admission) == "processed"

    assert _queued(admission) is None
    assert _queue_row(admission, OTHER_QUEUE) is not None
