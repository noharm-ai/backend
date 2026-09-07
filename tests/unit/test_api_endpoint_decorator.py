"""Unit tests for the ``api_endpoint`` decorator.

Every route in the application is wrapped in ``@api_endpoint()``, which owns:

* authentication — ``verify_jwt_in_request`` plus resolving the ``User``;
* the request schema — ``dbSession.setSchema(user_context.schema)``, the
  multi-tenancy switch;
* the transaction — commit on success, rollback on every failure, and running
  the post-commit callbacks only after a successful commit;
* the response envelope — ``{"status", "data"}`` on success, ``{"status",
  "message", "code"}`` on failure, each with its HTTP status;
* the authorization backstop — a handler that never went through
  ``@has_permission`` is refused rather than served.

These are unit tests: ``db``, ``dbSession``, ``User`` and the JWT helpers are
replaced with mocks so each branch can be driven directly, and the decorated
function is a locally defined handler rather than a real route. The
``ValidationError`` → HTTP mapping and the schema switch are behaviour clients
depend on, so they are asserted explicitly.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from flask import g
from flask_jwt_extended.exceptions import NoAuthorizationError
from jwt.exceptions import ExpiredSignatureError
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from config import Config
from decorators import api_endpoint_decorator
from decorators.api_endpoint_decorator import api_endpoint
from exception.authorization_error import AuthorizationError
from exception.validation_error import ValidationError
from models.enums import NoHarmENV
from mobile import app
from utils import post_commit, status


class _Model(BaseModel):
    """Minimal pydantic model, used to produce a real PydanticValidationError."""

    quantity: int


def _pydantic_error():
    """Return a genuine PydanticValidationError instead of a fabricated one."""
    try:
        _Model(quantity="not-a-number")
    except PydanticValidationError as e:
        return e
    raise AssertionError("expected pydantic to reject the payload")


def _user(id=42, schema="demo"):
    """Build the user the decorator resolves from the JWT identity."""
    user = MagicMock()
    user.id = id
    user.schema = schema
    return user


def _run(handler, *, user=None, path="/some/endpoint", method="GET", data=None):
    """Invoke a decorated handler with the decorator's collaborators mocked.

    Returns ``(result, mocks)`` where ``mocks`` exposes ``db``, ``db_session``
    (the ``dbSession`` schema switcher) and ``logger`` for assertions.
    """
    mock_db = MagicMock()
    mock_db_session = MagicMock()
    user = _user() if user is None else user

    with app.test_request_context(path=path, method=method, data=data):
        # every handler under test is expected to have passed the permission
        # gate; the tests that exercise the backstop clear this explicitly
        g.permission_test_count = 1

        with patch.object(api_endpoint_decorator, "db", mock_db), patch.object(
            api_endpoint_decorator, "dbSession", mock_db_session
        ), patch.object(
            api_endpoint_decorator, "verify_jwt_in_request"
        ), patch.object(
            api_endpoint_decorator, "get_jwt_identity", return_value=1
        ), patch.object(
            api_endpoint_decorator, "User"
        ) as mock_user_cls, patch.object(
            api_endpoint_decorator.logger, "backend_logger"
        ) as mock_logger:
            mock_user_cls.find.return_value = user
            result = handler()

    return result, MagicMock(db=mock_db, db_session=mock_db_session, logger=mock_logger)


# --------------------------------------------------------------------------
# success path
# --------------------------------------------------------------------------


def test_success_wraps_the_result_in_the_standard_envelope():
    """A handler's return value is nested under ``data`` with a 200."""

    @api_endpoint()
    def handler():
        return {"id": 7}

    result, _ = _run(handler)

    assert result == ({"status": "success", "data": {"id": 7}}, status.HTTP_200_OK)


def test_success_commits_and_releases_the_session():
    """The transaction is committed, then the session is closed and removed."""

    @api_endpoint()
    def handler():
        return None

    _, mocks = _run(handler)

    mocks.db.session.commit.assert_called_once()
    mocks.db.session.close.assert_called_once()
    mocks.db.session.remove.assert_called_once()
    mocks.db.session.rollback.assert_not_called()


def test_success_sets_the_request_schema():
    """Multi-tenancy hinges on this: the user's schema drives every query."""

    @api_endpoint()
    def handler():
        return None

    _, mocks = _run(handler, user=_user(schema="hospital_x"))

    mocks.db_session.setSchema.assert_called_once_with("hospital_x")


def test_the_user_context_is_injected_only_when_the_handler_asks_for_it():
    """Handlers opt in by declaring ``user_context``; others are called bare."""
    user = _user(id=99)
    seen = {}

    @api_endpoint()
    def wants_context(user_context=None):
        seen["user_context"] = user_context
        return None

    _run(wants_context, user=user)
    assert seen["user_context"] is user

    @api_endpoint()
    def takes_no_context(**kwargs):
        seen["kwargs"] = kwargs
        return None

    _run(takes_no_context, user=user)
    assert seen["kwargs"] == {}


def test_falsy_results_are_still_reported_as_success():
    """An empty list is a valid payload, not an error."""

    @api_endpoint()
    def handler():
        return []

    result, _ = _run(handler)

    assert result == ({"status": "success", "data": []}, status.HTTP_200_OK)


# --------------------------------------------------------------------------
# post-commit callbacks
# --------------------------------------------------------------------------


def test_post_commit_callbacks_run_after_a_successful_commit():
    """Callbacks registered by the handler fire once the commit lands."""
    calls = []

    @api_endpoint()
    def handler():
        post_commit.on_commit(lambda: calls.append("dispatched"))
        return None

    _run(handler)

    assert calls == ["dispatched"]


def test_post_commit_callbacks_do_not_run_when_the_handler_fails():
    """On the rollback path the registered side effects must be abandoned."""
    calls = []

    @api_endpoint()
    def handler():
        post_commit.on_commit(lambda: calls.append("dispatched"))
        raise ValidationError("nope", "errors.businessRules", 400)

    _run(handler)

    assert calls == []


# --------------------------------------------------------------------------
# authorization backstop
# --------------------------------------------------------------------------


def test_a_handler_that_skipped_the_permission_gate_is_refused():
    """A route whose service is missing ``@has_permission`` returns 401.

    ``permission_test_count`` is bumped by the permission decorator; zero means
    no permission was ever checked, which is treated as a programming error and
    refused rather than served.
    """
    mock_db = MagicMock()

    @api_endpoint()
    def handler():
        return {"leaked": True}

    with app.test_request_context():
        # deliberately not setting g.permission_test_count
        with patch.object(api_endpoint_decorator, "db", mock_db), patch.object(
            api_endpoint_decorator, "dbSession"
        ), patch.object(api_endpoint_decorator, "verify_jwt_in_request"), patch.object(
            api_endpoint_decorator, "get_jwt_identity", return_value=1
        ), patch.object(api_endpoint_decorator, "User") as mock_user_cls, patch.object(
            api_endpoint_decorator.logger, "backend_logger"
        ):
            mock_user_cls.find.return_value = _user()
            body, http_status = handler()

    assert http_status == status.HTTP_401_UNAUTHORIZED
    assert body["code"] == "error.authorizationError"
    # the handler ran, so its work must be rolled back rather than committed
    mock_db.session.commit.assert_not_called()
    mock_db.session.rollback.assert_called_once()


def test_an_authorization_error_from_the_service_becomes_a_401():
    """``@has_permission`` raising propagates as the 401 envelope."""

    @api_endpoint()
    def handler():
        raise AuthorizationError()

    (body, http_status), mocks = _run(handler)

    assert http_status == status.HTTP_401_UNAUTHORIZED
    assert body == {
        "status": "error",
        "message": "Usuário não autorizado neste recurso",
        "code": "error.authorizationError",
    }
    mocks.db.session.rollback.assert_called_once()


# --------------------------------------------------------------------------
# admin endpoints
# --------------------------------------------------------------------------


def test_admin_endpoints_are_blocked_in_production():
    """``is_admin`` routes are support tooling and must not exist in prod.

    The check runs before ``verify_jwt_in_request``, so no valid token can
    reach the handler.
    """
    called = []

    @api_endpoint(is_admin=True)
    def handler():
        called.append(True)
        return None

    with app.test_request_context():
        with patch.object(Config, "ENV", NoHarmENV.PRODUCTION.value), patch.object(
            api_endpoint_decorator, "db"
        ), patch.object(
            api_endpoint_decorator, "verify_jwt_in_request"
        ) as mock_verify, patch.object(
            api_endpoint_decorator.logger, "backend_logger"
        ):
            body, http_status = handler()

    assert http_status == status.HTTP_401_UNAUTHORIZED
    assert body["code"] == "error.authorizationError"
    assert called == []
    mock_verify.assert_not_called()


def test_admin_endpoints_are_allowed_outside_production():
    """The same route is served normally in the non-production environments."""

    @api_endpoint(is_admin=True)
    def handler():
        return "ok"

    result, _ = _run(handler)

    assert result == ({"status": "success", "data": "ok"}, status.HTTP_200_OK)


# --------------------------------------------------------------------------
# error mapping
# --------------------------------------------------------------------------


def test_a_validation_error_keeps_its_code_and_http_status():
    """Business errors are surfaced verbatim so the UI can translate them."""

    @api_endpoint()
    def handler():
        raise ValidationError(
            "Prescrição inexistente",
            "errors.invalidPrescription",
            status.HTTP_400_BAD_REQUEST,
        )

    (body, http_status), mocks = _run(handler)

    assert http_status == status.HTTP_400_BAD_REQUEST
    assert body == {
        "status": "error",
        "message": "Prescrição inexistente",
        "code": "errors.invalidPrescription",
    }
    mocks.db.session.rollback.assert_called_once()
    mocks.db.session.commit.assert_not_called()


def test_a_validation_error_can_carry_a_non_400_status():
    """The status comes from the exception, not from a fixed mapping."""

    @api_endpoint()
    def handler():
        raise ValidationError(
            "Registro em uso", "errors.businessRules", status.HTTP_409_CONFLICT
        )

    (_, http_status), _ = _run(handler)

    assert http_status == status.HTTP_409_CONFLICT


def test_a_pydantic_error_returns_the_field_validations():
    """Request-model failures return 400 plus the per-field detail."""

    @api_endpoint()
    def handler():
        raise _pydantic_error()

    (body, http_status), mocks = _run(handler)

    assert http_status == status.HTTP_400_BAD_REQUEST
    assert body["status"] == "error"
    assert body["message"] == "Parâmetros inválidos"
    assert [v["loc"] for v in body["validations"]] == [("quantity",)]
    mocks.db.session.rollback.assert_called_once()


@pytest.mark.parametrize(
    "error",
    [NoAuthorizationError("missing token"), ExpiredSignatureError("expired")],
    ids=["flask_jwt_extended", "pyjwt"],
)
def test_jwt_failures_report_an_expired_login(error):
    """Both JWT exception families map to the same 401 the client acts on."""

    @api_endpoint()
    def handler():
        return None

    mock_db = MagicMock()
    with app.test_request_context():
        g.permission_test_count = 1
        with patch.object(api_endpoint_decorator, "db", mock_db), patch.object(
            api_endpoint_decorator, "dbSession"
        ), patch.object(
            api_endpoint_decorator, "verify_jwt_in_request", side_effect=error
        ), patch.object(api_endpoint_decorator.logger, "backend_logger"):
            body, http_status = handler()

    assert http_status == status.HTTP_401_UNAUTHORIZED
    assert body == {
        "status": "error",
        "message": "Login expirado",
        "code": "error.authorizationError",
    }
    mock_db.session.rollback.assert_called_once()


def test_an_unexpected_exception_does_not_leak_its_message():
    """Internal failures return a generic 500; the detail only goes to the log."""

    @api_endpoint()
    def handler():
        raise RuntimeError("connection to db-primary.internal refused")

    (body, http_status), mocks = _run(handler)

    assert http_status == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert body == {"status": "error", "message": "Ocorreu um erro inesperado"}
    assert "db-primary.internal" not in json.dumps(body)
    mocks.db.session.rollback.assert_called_once()
    mocks.logger.exception.assert_called_once_with(
        "connection to db-primary.internal refused"
    )


def test_an_unexpected_exception_logs_the_query_string():
    """GET filters are needed to reproduce timeouts, so they are logged too."""

    @api_endpoint()
    def handler():
        raise RuntimeError("timeout")

    _, mocks = _run(handler, path="/prescriptions?idSegment=1&status=s")

    logged = [call.args for call in mocks.logger.error.call_args_list]
    assert any("idSegment=1&status=s" in str(args) for args in logged)


# --------------------------------------------------------------------------
# download responses
# --------------------------------------------------------------------------


def test_download_headers_are_applied_to_a_raw_response():
    """File downloads bypass the envelope and carry the given headers."""
    headers = {
        "Content-Type": "text/csv",
        "Content-Disposition": "attachment; filename=report.csv",
    }

    @api_endpoint(download_headers=headers)
    def handler():
        return "id;name\n1;Fulano Beltrano\n"

    response, _ = _run(handler)

    assert response.status_code == status.HTTP_200_OK
    assert response.headers["Content-Type"] == "text/csv"
    assert response.headers["Content-Disposition"] == "attachment; filename=report.csv"
    # the payload is the handler's own return value, not the success envelope
    assert response.get_data(as_text=True) == "id;name\n1;Fulano Beltrano\n"


def test_a_failing_download_endpoint_still_returns_the_error_envelope():
    """``download_headers`` only applies to the success path."""

    @api_endpoint(download_headers={"Content-Type": "text/csv"})
    def handler():
        raise ValidationError(
            "Sem dados", "errors.businessRules", status.HTTP_400_BAD_REQUEST
        )

    (body, http_status), _ = _run(handler)

    assert http_status == status.HTTP_400_BAD_REQUEST
    assert body["code"] == "errors.businessRules"


# --------------------------------------------------------------------------
# request logging
# --------------------------------------------------------------------------


def test_every_request_logs_a_completion_event():
    """The ``finally`` block reports the request regardless of the outcome."""

    @api_endpoint()
    def handler():
        return None

    _, mocks = _run(handler, path="/some/endpoint", method="GET")

    events = [json.loads(call.args[0]) for call in mocks.logger.warning.call_args_list]
    complete = [e for e in events if e.get("event") == "request_complete"]

    assert len(complete) == 1
    assert complete[0]["path"] == "/some/endpoint"
    assert complete[0]["method"] == "GET"
    assert complete[0]["schema"] == "demo"
    assert complete[0]["user"] == 42
    assert complete[0]["duration_ms"] >= 0


def test_a_request_that_failed_before_authentication_logs_an_undefined_user():
    """With no resolved user the log must not blow up on the missing context."""

    @api_endpoint()
    def handler():
        return None

    with app.test_request_context(path="/some/endpoint"):
        g.permission_test_count = 1
        with patch.object(api_endpoint_decorator, "db"), patch.object(
            api_endpoint_decorator, "dbSession"
        ), patch.object(
            api_endpoint_decorator,
            "verify_jwt_in_request",
            side_effect=NoAuthorizationError("missing token"),
        ), patch.object(api_endpoint_decorator.logger, "backend_logger") as mock_logger:
            handler()

    events = [json.loads(call.args[0]) for call in mock_logger.warning.call_args_list]
    complete = [e for e in events if e.get("event") == "request_complete"]

    assert complete[0]["schema"] == "undefined"
    assert complete[0]["user"] == "undefined"
