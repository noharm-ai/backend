"""Tests: non-CPOE segment filtering (``IGNORE_NON_CPOE_SEGMENTS``)

A CPOE prescription aggregates the whole admission, so by default it pulls in
items prescribed under *every* segment. Tenants that keep non-CPOE segments
around only for legacy data do not want those items counted, and turn on the
``IGNORE_NON_CPOE_SEGMENTS`` feature.

Two functions in ``segment_service`` carry that decision, and around twenty
call sites (prescription view, check, drug list, navigation, intervention
outcome...) chain them in the same way::

    is_cpoe = segment_service.is_cpoe(id_segment=prescription.idSegment)
    ignore_segments = segment_service.get_ignored_segments(is_cpoe_flag=is_cpoe)

``get_ignored_segments`` answers ``None`` — "filter nothing" for every caller —
unless the prescription is CPOE *and* the feature is on; only then does it list
the segments to leave out.

The functions read the segment table and the tenant feature list, so they run
here against the real ``demo`` schema inside a request context carrying a real
JWT: ``get_segments`` is permission-gated and resolves its user from the token
claims. The seed schema has exactly one segment of each kind, which is what the
filter is about.
"""

import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask_jwt_extended import verify_jwt_in_request
from sqlalchemy import text

from mobile import app
from models.enums import FeatureEnum
from models.main import db
from security.role import Role
from services import segment_service
from tests.conftest import get_access, session, session_commit

SCHEMA = "demo"
IGNORE_NON_CPOE = FeatureEnum.IGNORE_NON_CPOE_SEGMENTS.value

# seed segments: 1 is a plain segment, 2 is the CPOE one
SEGMENT_ID = 1
CPOE_SEGMENT_ID = 2
UNKNOWN_SEGMENT_ID = 999999


@contextmanager
def _service_context(client, roles=None):
    """Run service calls as an authenticated user of the demo schema.

    ``get_segments`` goes through ``@has_permission``, which rebuilds the user
    from the JWT claims — so a verified token is all the gate needs. The
    session is reset afterwards: it is shared with the rest of the suite.
    """
    token = get_access(client, roles=roles or [Role.PRESCRIPTION_ANALYST.value])

    with app.test_request_context(headers={"Authorization": f"Bearer {token}"}):
        verify_jwt_in_request()
        db.session.connection(
            execution_options={"schema_translate_map": {None: SCHEMA}}
        )
        try:
            yield
        finally:
            db.session.rollback()
            db.session.remove()


def _read_features():
    """Return the feature list currently stored in the demo schema."""
    row = session.execute(
        text("SELECT valor FROM demo.memoria WHERE tipo = 'features'")
    ).first()
    return list(row[0]) if row else []


def _write_features(features):
    """Overwrite the demo schema feature list."""
    session.execute(
        text(
            "UPDATE demo.memoria SET valor = CAST(:value AS json) WHERE tipo = 'features'"
        ),
        {"value": json.dumps(features)},
    )
    session_commit()


@pytest.fixture
def ignore_non_cpoe_segments():
    """Enable IGNORE_NON_CPOE_SEGMENTS for the demo schema."""
    original = _read_features()
    _write_features(original + [IGNORE_NON_CPOE])
    yield
    _write_features(original)


@pytest.fixture
def no_ignore_non_cpoe_segments():
    """Make sure IGNORE_NON_CPOE_SEGMENTS is *not* enabled for the demo schema."""
    original = _read_features()
    _write_features([f for f in original if f != IGNORE_NON_CPOE])
    yield
    _write_features(original)


# ---------------------------------------------------------------------------
# is_cpoe
# ---------------------------------------------------------------------------


def test_is_cpoe_is_true_for_the_cpoe_segment(client):
    with _service_context(client):
        assert segment_service.is_cpoe(id_segment=CPOE_SEGMENT_ID) is True


def test_is_cpoe_is_false_for_a_regular_segment(client):
    with _service_context(client):
        assert segment_service.is_cpoe(id_segment=SEGMENT_ID) is False


def test_is_cpoe_is_false_for_an_unknown_segment(client):
    """A prescription pointing at a segment that is gone is not CPOE"""
    with _service_context(client):
        assert segment_service.is_cpoe(id_segment=UNKNOWN_SEGMENT_ID) is False


@pytest.mark.parametrize("id_segment", [None, 0])
def test_is_cpoe_is_false_without_a_segment(client, id_segment):
    """Conciliation and outpatient records carry no segment"""
    with _service_context(client):
        assert segment_service.is_cpoe(id_segment=id_segment) is False


# ---------------------------------------------------------------------------
# get_ignored_segments
# ---------------------------------------------------------------------------


def test_nothing_is_ignored_outside_cpoe(client, ignore_non_cpoe_segments):
    """A non-CPOE prescription reads a single segment, so there is nothing to
    leave out — even with the feature on"""
    with _service_context(client):
        assert segment_service.get_ignored_segments(is_cpoe_flag=False) is None


def test_nothing_is_ignored_without_the_feature(client, no_ignore_non_cpoe_segments):
    """The default CPOE behaviour is to aggregate every segment"""
    with _service_context(client):
        assert segment_service.get_ignored_segments(is_cpoe_flag=True) is None


def test_non_cpoe_segments_are_ignored_with_the_feature(
    client, ignore_non_cpoe_segments
):
    with _service_context(client):
        assert segment_service.get_ignored_segments(is_cpoe_flag=True) == [SEGMENT_ID]


def test_the_cpoe_segment_is_never_ignored(client, ignore_non_cpoe_segments):
    with _service_context(client):
        ignored = segment_service.get_ignored_segments(is_cpoe_flag=True)

    assert CPOE_SEGMENT_ID not in ignored


def test_every_segment_being_cpoe_ignores_nothing(client, ignore_non_cpoe_segments):
    """An empty list, not None: the callers pass it to a ``notin_`` filter.

    A tenant that migrated every segment to CPOE is the case behind it. The
    segment list is stubbed rather than flipped in the database: the seed rows
    are shared with the rest of the suite, and rewriting one changes the order
    an unordered ``SELECT`` returns them in.
    """
    all_cpoe = [
        SimpleNamespace(id=SEGMENT_ID, cpoe=True),
        SimpleNamespace(id=CPOE_SEGMENT_ID, cpoe=True),
    ]

    with _service_context(client):
        with patch.object(segment_service, "get_segments", return_value=all_cpoe):
            assert segment_service.get_ignored_segments(is_cpoe_flag=True) == []
