"""Database utilities"""

import logging
import time

from flask_sqlalchemy.session import Session
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from exception.validation_error import ValidationError
from models.main import db, dbSession
from utils import status

logger = logging.getLogger("noharm.backend")


def set_schema(schema: str):
    """
    Point the session at a tenant schema, after checking that it exists.

    Static entries take the schema from the event, so an unknown one must fail
    instead of querying the wrong tenant. The check runs in its own session and
    leaves the session's connection to the schema_translate_map.
    """
    probe_session = Session(db)
    result = probe_session.execute(
        text("SELECT schema_name FROM information_schema.schemata")
    )
    schema_exists = any(r[0] == schema for r in result)
    probe_session.close()

    if not schema_exists:
        raise ValidationError(
            "Schema Inexistente", "errors.invalidSchema", status.HTTP_400_BAD_REQUEST
        )

    dbSession.setSchema(schema)


def run_with_deadlock_retry(fn, max_retries=3, base_delay=0.1, on_retry=None):
    """
    Execute fn(), retrying on PostgreSQL deadlock (error code 40P01) up to
    max_retries times with exponential back-off.

    The session must be rolled back before retrying so that SQLAlchemy can
    start a fresh transaction.  fn() is responsible for re-reading any ORM
    objects it needs after a retry.

    on_retry: optional callable invoked after rollback and before each retry.
    Use it to re-establish any session-level context that rollback clears
    (e.g. schema_translate_map via dbSession.setSchema).
    """
    from models.main import db

    for attempt in range(max_retries):
        try:
            return fn()
        except OperationalError as e:
            is_deadlock = "deadlock" in str(e).lower()
            if is_deadlock and attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                logger.warning(
                    "Deadlock detected (attempt %d/%d), retrying in %.2fs: %s",
                    attempt + 1,
                    max_retries,
                    delay,
                    e,
                )
                db.session.rollback()
                if on_retry:
                    on_retry()
                time.sleep(delay)
                continue
            raise
