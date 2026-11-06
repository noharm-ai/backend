"""Repository: admission queues (fila_atendimento), one per consumer"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Integer,
    any_,
    case,
    delete,
    func,
    literal,
    select,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY, insert
from sqlalchemy.sql.elements import ColumnElement

from models.admission_queue import AdmissionQueue
from models.enums import AdmissionQueueEnum, AdmissionQueueReasonEnum
from models.main import db


def enqueue(
    queue: AdmissionQueueEnum,
    admission_number: int,
    reason: AdmissionQueueReasonEnum,
    now: datetime,
    only_if: ColumnElement[bool] | None = None,
) -> bool:
    """Queue the admission for a consumer, adding the reason to the ones
    already queued. With `only_if` (a condition on the admission, evaluated in
    the same statement) it is queued only when the condition holds.

    Returns True when it was queued.
    """
    stmt = insert(AdmissionQueue).from_select(
        ["tp_fila", "nratendimento", "dt_fila", "motivos", "created_at"],
        select(
            literal(queue.value, Integer),
            literal(admission_number, BigInteger),
            literal(now, DateTime),
            literal([reason.value], ARRAY(db.String(50))),
            literal(now, DateTime),
        ).where(only_if if only_if is not None else true()),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["tp_fila", "nratendimento"],
        set_={
            "dt_fila": stmt.excluded.dt_fila,
            "motivos": case(
                (
                    literal(reason.value) == any_(AdmissionQueue.reasons),
                    AdmissionQueue.reasons,
                ),
                else_=func.array_append(AdmissionQueue.reasons, reason.value),
            ),
        },
    )
    return db.session.execute(stmt).rowcount > 0


def get_queued_at(queue: AdmissionQueueEnum, admission_number: int) -> datetime | None:
    """When the admission was last queued for a consumer, None when it is not
    queued"""
    return (
        db.session.query(AdmissionQueue.queued_at)
        .filter(
            AdmissionQueue.queue == queue.value,
            AdmissionQueue.admission_number == admission_number,
        )
        .scalar()
    )


def dequeue(
    queue: AdmissionQueueEnum, admission_number: int, queued_at: datetime
) -> bool:
    """Remove the admission from a consumer's queue, unless it was queued again
    after `queued_at` (the change is still to be seen) or is being queued right
    now (its row is locked: it will be, so it is not waited for).

    Returns True when it was removed.
    """
    unchanged = (
        select(AdmissionQueue.admission_number)
        .where(
            AdmissionQueue.queue == queue.value,
            AdmissionQueue.admission_number == admission_number,
            AdmissionQueue.queued_at == queued_at,
        )
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    stmt = (
        delete(AdmissionQueue)
        .where(
            AdmissionQueue.queue == queue.value,
            AdmissionQueue.admission_number == unchanged,
        )
        .execution_options(synchronize_session=False)
    )
    return db.session.execute(stmt).rowcount > 0
