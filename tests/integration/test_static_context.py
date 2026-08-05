"""Integration tests for utils.static_context.

``static_context`` is the plumbing used by the ``/static`` event endpoints
(see ``static.py``): it spins up a real Flask app context, mints a JWT for a
synthetic ``STATIC_USER`` (id 0), verifies it, runs an operation with that
user context injected, and serialises the result into the standard NoHarm
response envelope. Because it commits against the database session and relies
on the JWT extension, it is exercised here as an integration test rather than
a pure unit test.
"""

import json

import pytest

from exception.authorization_error import AuthorizationError
from exception.validation_error import ValidationError
from utils import status
from utils.static_context import execute_with_static_context, static_user_context

SCHEMA = "demo"


class TestStaticUserContext:
    """static_user_context - the synthetic authenticated user it yields."""

    def test_yields_static_user_for_requested_schema(self):
        """The yielded user is the id-0 STATIC_USER bound to the schema."""
        with static_user_context(SCHEMA) as user_context:
            assert user_context.id == 0
            assert user_context.schema == SCHEMA
            assert user_context.config == {"roles": ["STATIC_USER"]}


class TestExecuteWithStaticContextSuccess:
    """execute_with_static_context - the happy path envelope."""

    def test_returns_success_envelope_with_operation_result(self):
        """A successful operation is wrapped as status=success / httpCode=200."""

        def operation(user_context):
            return {"schema": user_context.schema, "value": 42}

        raw = execute_with_static_context(SCHEMA, operation, {})
        payload = json.loads(raw)

        assert payload["status"] == "success"
        assert payload["httpCode"] == status.HTTP_200_OK
        assert payload["data"] == {"schema": SCHEMA, "value": 42}

    def test_injects_user_context_and_forwards_extra_params(self):
        """The operation receives the static user plus any caller params."""

        def operation(user_context, factor):
            return {"id": user_context.id, "result": factor * 2}

        raw = execute_with_static_context(SCHEMA, operation, {"factor": 21})
        payload = json.loads(raw)

        assert payload["status"] == "success"
        assert payload["data"] == {"id": 0, "result": 42}


class TestExecuteWithStaticContextErrors:
    """execute_with_static_context - exception handling branches."""

    def test_validation_error_maps_to_its_http_status(self):
        """A ValidationError surfaces its message and configured http status."""

        def operation(user_context):
            raise ValidationError(
                "campo obrigatório",
                "errors.invalidParams",
                status.HTTP_400_BAD_REQUEST,
            )

        payload = json.loads(execute_with_static_context(SCHEMA, operation, {}))

        assert payload["status"] == "error"
        assert payload["message"] == "campo obrigatório"
        assert payload["httpCode"] == status.HTTP_400_BAD_REQUEST

    def test_validation_error_preserves_custom_http_status(self):
        """The httpStatus carried by the ValidationError is not overwritten."""

        def operation(user_context):
            raise ValidationError(
                "não autorizado",
                "errors.businessRules",
                status.HTTP_401_UNAUTHORIZED,
            )

        payload = json.loads(execute_with_static_context(SCHEMA, operation, {}))

        assert payload["httpCode"] == status.HTTP_401_UNAUTHORIZED

    def test_authorization_error_maps_to_401(self):
        """An AuthorizationError becomes a generic 401 'invalid user' response."""

        def operation(user_context):
            raise AuthorizationError()

        payload = json.loads(execute_with_static_context(SCHEMA, operation, {}))

        assert payload["status"] == "error"
        assert payload["message"] == "Usuário inválido"
        assert payload["httpCode"] == status.HTTP_401_UNAUTHORIZED

    def test_unexpected_exception_maps_to_500(self):
        """Any other exception is masked as a generic 500 error."""

        def operation(user_context):
            raise RuntimeError("boom")

        payload = json.loads(execute_with_static_context(SCHEMA, operation, {}))

        assert payload["status"] == "error"
        assert payload["message"] == "Erro inesperado"
        assert payload["httpCode"] == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_error_response_is_json_serialisable_string(self):
        """The envelope is always returned as a JSON string, even on error."""

        def operation(user_context):
            raise RuntimeError("boom")

        raw = execute_with_static_context(SCHEMA, operation, {})

        assert isinstance(raw, str)
        # round-trips without raising
        assert json.loads(raw)["status"] == "error"
