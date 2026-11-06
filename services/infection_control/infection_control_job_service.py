"""Service: infection control job, one admission of the scheduled sync

The scheduled job in backend-private lists the admissions of each schema (the
full run every followed one, the light run the ones queued for it in
fila_atendimento, see admission_queue_service) and calls
static.infection_control_sync for one admission at a time, waiting for each, so
a single backend invocation (and database session) per run is at work at once.
The rule itself lives only in this repository.

Either run dequeues the admission it applied the rule to, unless prescalc
queued it again meanwhile: that change may have come after the rule read the
prescriptions, so it stays for the next run.
"""

from datetime import datetime

from sqlalchemy.exc import OperationalError

from decorators.has_permission_decorator import Permission, has_permission
from models.enums import AdmissionQueueEnum, InfectionControlOriginEnum
from models.main import User, db
from repository import admission_queue_repository
from services.infection_control import infection_control_status_service as rule
from utils import db_utils

JOB_USER_ID = 0
# a review save holding the record must not hold the job up
JOB_LOCK_TIMEOUT_MS = 2000
# postgres lock_not_available, raised when lock_timeout runs out
LOCK_NOT_AVAILABLE = "55P03"


@has_permission(Permission.READ_STATIC)
def sync_followed_admission(
    schema: str,
    admission_number: int,
    user_context: User,
    lock_timeout_ms: int = JOB_LOCK_TIMEOUT_MS,
) -> str:
    """Apply the rule to one followed admission, returning "processed",
    "changed" or "skipped" (not followed, or held by a writer: the next run
    tries again), and dequeue it"""
    db_utils.set_schema(schema)

    now = datetime.now()
    # read before the rule reads the prescriptions: queued again after this,
    # it stays queued
    queued_at = admission_queue_repository.get_queued_at(
        queue=AdmissionQueueEnum.INFECTION_CONTROL, admission_number=admission_number
    )

    try:
        admission = rule.sync_admission(
            admission_number=admission_number,
            origin=InfectionControlOriginEnum.JOB,
            user_id=JOB_USER_ID,
            now=now,
            lock_timeout_ms=lock_timeout_ms,
        )
    except OperationalError as e:
        if getattr(e.orig, "pgcode", None) != LOCK_NOT_AVAILABLE:
            raise

        # held by a writer: it stays queued
        db.session.rollback()
        return "skipped"

    if queued_at is not None:
        admission_queue_repository.dequeue(
            queue=AdmissionQueueEnum.INFECTION_CONTROL,
            admission_number=admission_number,
            queued_at=queued_at,
        )

    # not followed: dequeued too, there is nothing to run until prescalc
    # follows it again
    if admission is None:
        return "skipped"

    # apply_rule moves status_date only when the status changes
    return "changed" if admission.status_date == now else "processed"
