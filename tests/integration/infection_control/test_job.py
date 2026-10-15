"""Tests: infection control follow-up, the scheduled job's entry
(static.infection_control_sync), called by backend-private one admission at a
time"""

import json

from models.main import db
from services.infection_control import infection_control_job_service
from static import infection_control_sync
from tests.conftest import session_commit
from tests.integration.infection_control.helpers import (
    CLOSED,
    NO_EVALUATION,
    PENDING,
    _hold_record,
    _open_pendings,
    _prescribe_today,
    _record,
    _suspend,
)
from utils.static_context import static_user_context


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


def test_job_applies_rule_to_followed_admission(infection_control, admission):
    """The entry runs the rule on the admission and commits it"""
    _prescribe_today(admission, job=False)
    assert NO_EVALUATION not in [p["tp_pendencia"] for p in _open_pendings(admission)]

    assert _sync(admission) == "processed"

    assert NO_EVALUATION in [p["tp_pendencia"] for p in _open_pendings(admission)]
    assert _record(admission)["tp_status"] == PENDING


def test_job_closes_admission_when_drug_stops(infection_control, admission):
    """A stopped drug closes the record, reported as a change"""
    id_prescription = _prescribe_today(admission)
    _suspend(id_prescription)

    assert _sync(admission) == "changed"

    assert _record(admission)["tp_status"] == CLOSED


def test_job_skips_admission_not_followed(infection_control, admission):
    """An admission without a record and nothing running is left alone"""
    assert _sync(admission) == "skipped"

    assert _record(admission) is None


def test_job_skips_admission_held_by_a_writer(infection_control, admission):
    """A record locked by a review save is skipped after the lock timeout, not waited for"""
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
    assert NO_EVALUATION not in [p["tp_pendencia"] for p in _open_pendings(admission)]


def test_job_rejects_unknown_schema(infection_control, admission):
    """A schema that does not exist is refused before any query, as in prescalc"""
    response = json.loads(
        infection_control_sync(
            {"schema": "does_not_exist", "admission_number": admission}, None
        )
    )

    assert response["status"] == "error"
    assert response["message"] == "Schema Inexistente"
