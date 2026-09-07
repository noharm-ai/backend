"""Unit tests for the post-commit callback registry.

Some work must only happen once the request transaction is durably committed —
dispatching an async event that references rows the worker will read back, for
instance. ``utils.post_commit`` is the registry for that: services call
``on_commit(callback)`` during the request, and the two transaction owners
(``api_endpoint`` and ``execute_with_static_context``) call
``run_post_commit_callbacks()`` immediately after a successful commit.

The registry lives on Flask's ``g``, so it is request-scoped: a rollback
discards the request context and the callbacks simply never run. These tests
pin that contract down, plus the guarantee that a callback blowing up cannot
turn an already-committed transaction into a failed request.
"""

from unittest.mock import patch

import pytest
from flask import g

from mobile import app
from utils import post_commit


@pytest.fixture
def request_context():
    """Run each test inside its own request context (its own ``g``)."""
    with app.test_request_context():
        yield


# --------------------------------------------------------------------------
# registration
# --------------------------------------------------------------------------


def test_run_without_any_callback_is_a_noop(request_context):
    """A request that registered nothing must not fail on the run call."""
    post_commit.run_post_commit_callbacks()


def test_on_commit_creates_the_registry_on_first_use(request_context):
    """``g`` starts clean; the first ``on_commit`` seeds the list."""
    assert not hasattr(g, "post_commit_callbacks")

    def callback():
        pass

    post_commit.on_commit(callback)

    assert g.post_commit_callbacks == [callback]


def test_callbacks_run_in_registration_order(request_context):
    """Order matters: services may register dependent side effects."""
    calls = []

    post_commit.on_commit(lambda: calls.append("first"))
    post_commit.on_commit(lambda: calls.append("second"))
    post_commit.on_commit(lambda: calls.append("third"))

    post_commit.run_post_commit_callbacks()

    assert calls == ["first", "second", "third"]


def test_the_same_callback_registered_twice_runs_twice(request_context):
    """No de-duplication: two registrations mean two side effects."""
    calls = []

    def callback():
        calls.append(1)

    post_commit.on_commit(callback)
    post_commit.on_commit(callback)

    post_commit.run_post_commit_callbacks()

    assert calls == [1, 1]


# --------------------------------------------------------------------------
# draining
# --------------------------------------------------------------------------


def test_the_registry_is_drained_after_running(request_context):
    """Callbacks fire exactly once, even if the run is called again."""
    calls = []
    post_commit.on_commit(lambda: calls.append(1))

    post_commit.run_post_commit_callbacks()
    post_commit.run_post_commit_callbacks()

    assert calls == [1]
    assert g.post_commit_callbacks == []


def test_a_callback_registering_another_one_defers_it(request_context):
    """The registry is swapped out before the run, so a nested registration
    lands in the next batch instead of extending the current one."""
    calls = []

    def outer():
        calls.append("outer")
        post_commit.on_commit(lambda: calls.append("nested"))

    post_commit.on_commit(outer)
    post_commit.run_post_commit_callbacks()

    # the nested callback did not run in this pass, but is queued
    assert calls == ["outer"]
    assert len(g.post_commit_callbacks) == 1

    post_commit.run_post_commit_callbacks()

    assert calls == ["outer", "nested"]


# --------------------------------------------------------------------------
# failure isolation — the transaction is already committed
# --------------------------------------------------------------------------


def test_a_failing_callback_does_not_propagate(request_context):
    """The commit already happened, so a callback error cannot fail the request."""

    def boom():
        raise RuntimeError("sqs unavailable")

    post_commit.on_commit(boom)

    with patch.object(post_commit.logger, "backend_logger") as mock_logger:
        post_commit.run_post_commit_callbacks()

    mock_logger.exception.assert_called_once_with("post-commit callback failed")


def test_a_failing_callback_does_not_stop_the_remaining_ones(request_context):
    """Each callback is independent: one failure must not swallow the others."""
    calls = []

    def boom():
        raise RuntimeError("sqs unavailable")

    post_commit.on_commit(lambda: calls.append("before"))
    post_commit.on_commit(boom)
    post_commit.on_commit(lambda: calls.append("after"))

    with patch.object(post_commit.logger, "backend_logger"):
        post_commit.run_post_commit_callbacks()

    assert calls == ["before", "after"]


def test_a_failing_callback_is_still_drained(request_context):
    """A failed callback is not retried on the next run."""

    def boom():
        raise RuntimeError("sqs unavailable")

    post_commit.on_commit(boom)

    with patch.object(post_commit.logger, "backend_logger") as mock_logger:
        post_commit.run_post_commit_callbacks()
        post_commit.run_post_commit_callbacks()

    assert mock_logger.exception.call_count == 1


# --------------------------------------------------------------------------
# request scoping
# --------------------------------------------------------------------------


def test_callbacks_do_not_leak_between_requests():
    """``g`` is per-request, so an unrun callback dies with its request.

    This is what makes the rollback path safe: the transaction owner only calls
    the runner after a successful commit, and anything registered during a
    failed request is discarded with the context.
    """
    calls = []

    with app.test_request_context():
        post_commit.on_commit(lambda: calls.append("abandoned"))
        # request ends without the runner ever being called (rollback path)

    with app.test_request_context():
        post_commit.run_post_commit_callbacks()

    assert calls == []
