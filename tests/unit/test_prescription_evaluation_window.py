"""Unit tests for prescription_service.is_being_evaluated

The prescription list and the prioritization queue both decorate a row with
``isBeingEvaluated`` so a pharmacist can see that someone else is already on it.
The flag is computed from the ``evaluation.startDate`` kept in the prescription's
``features`` JSON, and it goes stale on its own after five minutes -- nothing
ever clears it, so the window *is* the feature.

The function is deprecated in favour of the DynamoDB presence store, but both
call sites still use it, so its edges are worth holding still.
"""

from datetime import datetime, timedelta

import pytest

from services.prescription_service import is_being_evaluated

WINDOW_MINUTES = 5


def _features(minutes_ago: float):
    """A features JSON whose evaluation started ``minutes_ago`` minutes back."""
    started = datetime.today() - timedelta(minutes=minutes_ago)

    return {"evaluation": {"startDate": started.isoformat()}}


# --- nothing recorded ---------------------------------------------------------


@pytest.mark.parametrize(
    "features",
    [None, {}, {"evaluation": {}}, {"evaluation": {"other": "x"}}],
    ids=["no features", "no evaluation", "empty evaluation", "no startDate"],
)
def test_a_prescription_nobody_opened_is_not_being_evaluated(features):
    """Absent data means "free", never an error: the flag decorates every row."""
    assert is_being_evaluated(features) is False


# --- the five-minute window ---------------------------------------------------


def test_an_evaluation_started_moments_ago_is_active():
    """The normal case: a colleague has the prescription open right now."""
    assert is_being_evaluated(_features(minutes_ago=1)) is True


def test_an_evaluation_older_than_the_window_has_lapsed():
    """Nothing clears the marker, so it has to expire by itself."""
    assert is_being_evaluated(_features(minutes_ago=WINDOW_MINUTES * 2)) is False


def test_the_window_edge_still_counts_as_active():
    """The boundary is inclusive; pinned so a refactor cannot quietly flip it."""
    assert is_being_evaluated(_features(minutes_ago=WINDOW_MINUTES - 0.01)) is True


def test_just_past_the_window_is_inactive():
    """One tick past the boundary and the prescription is free again."""
    assert is_being_evaluated(_features(minutes_ago=WINDOW_MINUTES + 0.01)) is False


def test_a_start_date_in_the_future_is_treated_as_active():
    """Clock skew between the app servers must not free a prescription someone
    is holding: a future timestamp stays inside the window rather than falling
    outside it."""
    assert is_being_evaluated(_features(minutes_ago=-30)) is True


# --- malformed data -----------------------------------------------------------


def test_an_unparseable_start_date_raises():
    """The timestamp comes from the prescription's own features JSON, so a value
    that is not ISO-8601 is a data bug and is not silently read as "free"."""
    with pytest.raises(ValueError):
        is_being_evaluated({"evaluation": {"startDate": "not-a-date"}})
