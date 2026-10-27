"""Service: infection control job, one admission of the scheduled sync

The scheduled job in backend-private lists the followed admissions of each
schema and calls static.infection_control_sync for one admission at a time,
waiting for each, so a single backend invocation (and database session) runs
at once. The rule itself lives only in this repository.
"""

from datetime import datetime

from sqlalchemy.exc import OperationalError

from decorators.has_permission_decorator import Permission, has_permission
from models.enums import InfectionControlOriginEnum
from models.main import User, db
from services.infection_control import infection_control_status_service as rule
from services.infection_control import infection_control_summary_service
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
    tries again)"""
    db_utils.set_schema(schema)

    now = datetime.now()

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

        db.session.rollback()
        return "skipped"

    if admission is None:
        return "skipped"

    # the summary's culture facts read DynamoDB, keyed by schema: once a day
    infection_control_summary_service.refresh_cultures(
        admission=admission, schema=schema, now=now
    )

    # apply_rule moves status_date only when the status changes
    return "changed" if admission.status_date == now else "processed"
