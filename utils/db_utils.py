"""Database utilities"""

import logging
import time
from contextlib import contextmanager

from flask_sqlalchemy.session import Session
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from exception.validation_error import ValidationError
from models.main import db, dbSession
from utils import status

logger = logging.getLogger("noharm.backend")

# postgres query_canceled, raised when statement_timeout runs out
QUERY_CANCELED = "57014"

# the settings local_timeout may change
_TIMEOUT_SETTINGS = ("lock_timeout", "statement_timeout")


# schemas this process already found in the database: a container runs the
# static entries (prescalc) over and over for the same schemas
_known_schemas: set[str] = set()


def set_schema(schema: str):
    """
    Point the session at a tenant schema, after checking that it exists.

    Static entries take the schema from the event, so an unknown one must fail
    instead of querying the wrong tenant. The check runs in its own session and
    leaves the session's connection to the schema_translate_map.

    A schema found once is not checked again by this process: the check is a
    connection checkout and a query of its own on every prescalc. Only
    existing schemas are remembered, so an unknown one is always looked up
    (and refused).
    """
    if schema not in _known_schemas:
        probe_session = Session(db)
        result = probe_session.execute(
            text("SELECT schema_name FROM information_schema.schemata")
        )
        schema_exists = any(r[0] == schema for r in result)
        probe_session.close()

        if not schema_exists:
            raise ValidationError(
                "Schema Inexistente",
                "errors.invalidSchema",
                status.HTTP_400_BAD_REQUEST,
            )

        _known_schemas.add(schema)

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


@contextmanager
def local_timeout(setting: str, timeout_ms: int | None):
    """Set a timeout (lock_timeout, statement_timeout) inside the block: running
    out raises OperationalError.

    Restored when the block succeeds, so it doesn't leak into the rest of the
    transaction. When it fails the transaction (or the savepoint the block runs
    in) is rolled back, and that undoes the setting too: run the block inside
    db.session.begin_nested() when the request carries on after the timeout.
    """
    if setting not in _TIMEOUT_SETTINGS:
        raise ValueError(f"unsupported timeout setting: {setting}")

    if timeout_ms is None:
        yield
        return

    # set_config(..., true) is SET LOCAL with a bind param
    db.session.execute(
        text("SELECT set_config(:setting, :timeout, true)"),
        {"setting": setting, "timeout": f"{int(timeout_ms)}ms"},
    )
    yield
    db.session.execute(text(f"SET LOCAL {setting} = DEFAULT"))


def lock_timeout(lock_timeout_ms: int | None):
    """Bound the lock waits inside the block (see local_timeout)"""
    return local_timeout("lock_timeout", lock_timeout_ms)


def statement_timeout(statement_timeout_ms: int | None):
    """Bound each query inside the block (see local_timeout)"""
    return local_timeout("statement_timeout", statement_timeout_ms)
