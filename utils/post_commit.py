"""Post-commit callback registry.

Some operations must only happen after the request/operation transaction is
durably committed (e.g. dispatching async events that reference the
committed data). Services register callbacks here; the transaction owners
(api_endpoint decorator and execute_with_static_context) run them right
after a successful db.session.commit(). On rollback the request context is
discarded and the callbacks never run.
"""

from flask import g

from utils import logger


def on_commit(callback):
    """Register a callback to run after the current transaction commits."""
    if not hasattr(g, "post_commit_callbacks"):
        g.post_commit_callbacks = []

    g.post_commit_callbacks.append(callback)


def run_post_commit_callbacks():
    """Run and clear registered callbacks. Failures are logged, never raised:
    the transaction is already committed."""
    callbacks = getattr(g, "post_commit_callbacks", [])
    g.post_commit_callbacks = []

    for callback in callbacks:
        try:
            callback()
        except Exception:
            logger.backend_logger.exception("post-commit callback failed")
