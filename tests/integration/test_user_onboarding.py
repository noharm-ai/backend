"""Integration tests for POST /user/complete-onboarding.

A user created while ``FEATURE_USER_ONBOARDING`` is on gets an ``onboarding``
row in ``public.usuario_atributo`` with the value ``pending``. That row is what
makes the onboarding training mandatory for them (see ``training_service``), and
this endpoint is how the frontend clears it once the user is through.

Two properties matter and neither is obvious from the endpoint's signature:

* it only ever moves ``pending`` → ``onboarded``. A user with no row is exempt
  from onboarding, and creating one here would hand them an onboarding they
  were never meant to see;
* it leaves an audit record, so support can tell a user who never onboarded
  apart from one who did it and had the row reset.

These are integration tests: they authenticate for real and read the rows back
from the database. The fixture restores the attribute row and removes the audit
records it caused, so the tests are re-runnable and leave no residue.
"""

import pytest
from sqlalchemy import text

from models.enums import UserAuditTypeEnum
from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit

URL = "/user/complete-onboarding"

# the user every fixture authenticates as (public.usuario)
DEMO_USER_ID = 1

PENDING = "pending"
ONBOARDED = "onboarded"


def _read_attribute():
    """The user's onboarding attribute row, or None when there is none."""
    session_commit()
    return session.execute(
        text(
            "SELECT valor, updated_at, updated_by FROM public.usuario_atributo "
            "WHERE idusuario = :uid AND tipo = 'onboarding'"
        ),
        {"uid": DEMO_USER_ID},
    ).first()


def _read_audits(since_id):
    """Audit records written for the user after ``since_id``."""
    session_commit()
    return session.execute(
        text(
            "SELECT tp_audit, extra, created_by FROM public.usuario_audit "
            "WHERE idusuario = :uid AND idusuario_audit > :since "
            "ORDER BY idusuario_audit"
        ),
        {"uid": DEMO_USER_ID, "since": since_id},
    ).all()


def _max_audit_id():
    session_commit()
    return (
        session.execute(
            text("SELECT COALESCE(MAX(idusuario_audit), 0) FROM public.usuario_audit")
        ).scalar()
        or 0
    )


@pytest.fixture
def onboarding_state():
    """Set the user's onboarding attribute, restoring the original after.

    Yields a setter taking the attribute value, or None for "no row at all" —
    the state of a user who predates the onboarding feature.
    """
    original = session.execute(
        text(
            "SELECT valor FROM public.usuario_atributo "
            "WHERE idusuario = :uid AND tipo = 'onboarding'"
        ),
        {"uid": DEMO_USER_ID},
    ).first()

    def _set(value):
        session.execute(
            text(
                "DELETE FROM public.usuario_atributo "
                "WHERE idusuario = :uid AND tipo = 'onboarding'"
            ),
            {"uid": DEMO_USER_ID},
        )

        if value is not None:
            session.execute(
                text(
                    "INSERT INTO public.usuario_atributo "
                    "(idusuario, tipo, valor, created_at, created_by) "
                    "VALUES (:uid, 'onboarding', :value, now(), :uid)"
                ),
                {"uid": DEMO_USER_ID, "value": value},
            )

        session_commit()

    yield _set

    _set(original[0] if original is not None else None)


class _AuditTrail:
    """Audit records written from a movable mark onwards."""

    def __init__(self, mark):
        self.mark = mark

    def reset(self):
        """Move the mark to now, so earlier records (a login) are ignored."""
        self.mark = _max_audit_id()

    def records(self):
        return _read_audits(self.mark)


@pytest.fixture
def audit_trail():
    """Read the audit records a test causes, removing them afterwards."""
    setup_mark = _max_audit_id()

    yield _AuditTrail(setup_mark)

    session.execute(
        text("DELETE FROM public.usuario_audit WHERE idusuario_audit > :since"),
        {"since": setup_mark},
    )
    session_commit()


# --------------------------------------------------------------------------
# access control
# --------------------------------------------------------------------------


def test_complete_onboarding_requires_authentication(client):
    """The endpoint is behind the standard JWT check [401 UNAUTHORIZED]."""
    response = client.post(URL)

    assert response.status_code == 401


def test_complete_onboarding_requires_read_basic_features(
    client, onboarding_state, audit_trail
):
    """A role without READ_BASIC_FEATURES cannot clear the flag [401]."""
    onboarding_state(PENDING)
    headers = make_headers(get_access(client, roles=[Role.DISPENSING_MANAGER.value]))
    audit_trail.reset()

    response = client.post(URL, headers=headers)

    assert response.status_code == 401
    assert _read_attribute()[0] == PENDING
    assert audit_trail.records() == []


# --------------------------------------------------------------------------
# the transition
# --------------------------------------------------------------------------


def test_complete_onboarding_marks_a_pending_user_as_onboarded(
    client, analyst_headers, onboarding_state, audit_trail
):
    """The pending row is updated in place, stamped with the user [200 OK]."""
    onboarding_state(PENDING)

    response = client.post(URL, headers=analyst_headers)

    assert response.status_code == 200
    assert response.get_json()["status"] == "success"

    value, updated_at, updated_by = _read_attribute()
    assert value == ONBOARDED
    assert updated_at is not None
    assert updated_by == DEMO_USER_ID


def test_complete_onboarding_records_an_audit_entry(
    client, analyst_headers, onboarding_state, audit_trail
):
    """Support needs to see that the user went through onboarding."""
    onboarding_state(PENDING)
    audit_trail.reset()

    client.post(URL, headers=analyst_headers)

    audits = audit_trail.records()
    assert len(audits) == 1

    audit_type, extra, created_by = audits[0]
    assert audit_type == UserAuditTypeEnum.UPDATE.value
    assert extra == {"onboarding": ONBOARDED}
    assert created_by == DEMO_USER_ID


def test_complete_onboarding_is_idempotent(
    client, analyst_headers, onboarding_state, audit_trail
):
    """A second call is a no-op: the flag is already cleared."""
    onboarding_state(PENDING)
    audit_trail.reset()

    assert client.post(URL, headers=analyst_headers).status_code == 200
    assert client.post(URL, headers=analyst_headers).status_code == 200

    assert _read_attribute()[0] == ONBOARDED
    # the repeat call must not stack a second audit record
    assert len(audit_trail.records()) == 1


# --------------------------------------------------------------------------
# users the onboarding does not apply to
# --------------------------------------------------------------------------


def test_complete_onboarding_does_not_create_a_row_for_an_exempt_user(
    client, analyst_headers, onboarding_state, audit_trail
):
    """No row means the user was never enrolled — the call leaves it that way.

    Writing ``onboarded`` here would be worse than a no-op: the mere presence
    of the row is what marks a user as new, so it would enrol them backwards.
    """
    onboarding_state(None)
    audit_trail.reset()

    response = client.post(URL, headers=analyst_headers)

    assert response.status_code == 200
    assert _read_attribute() is None
    assert audit_trail.records() == []


def test_complete_onboarding_leaves_an_unknown_status_untouched(
    client, analyst_headers, onboarding_state, audit_trail
):
    """Only ``pending`` is a transition the endpoint knows how to make."""
    onboarding_state("zztest-unknown-status")
    audit_trail.reset()

    response = client.post(URL, headers=analyst_headers)

    assert response.status_code == 200
    assert _read_attribute()[0] == "zztest-unknown-status"
    assert audit_trail.records() == []
