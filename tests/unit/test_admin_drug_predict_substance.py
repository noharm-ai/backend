"""Unit tests for ``admin_drug_service.predict_substance``.

``POST /admin/drug/predict-substance`` lets a curator ask the private backend
lambda to infer the substance of every drug in the schema that still has none.
The inference is slow, so the backend fires the lambda asynchronously and only
hands back the AWS request id, which the screen uses to follow the job.

What these tests pin down:

* the lambda is invoked asynchronously (``Event``), on the configured backend
  function, in the region the private lambdas live in;
* the payload names the inference command and the caller's own schema, so a
  curator can never trigger the inference for another schema;
* the AWS request id and status code are returned, and a response without
  metadata answers with nulls instead of failing;
* only a role holding ADMIN_DRUGS can fire it, and a denied call never reaches
  the lambda.

``utils.aws`` is mocked throughout, so no AWS access happens. The
``@has_permission(ADMIN_DRUGS)`` gate resolves the caller from the JWT identity,
so the JWT lookup and the ``User`` model are patched to inject a fabricated user
inside a Flask request context.
"""

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from config import Config
from exception.authorization_error import AuthorizationError
from mobile import app
from security.role import Role
from services.admin import admin_drug_service

INFER_COMMAND = "lambda_substances.infer_schema_substances"

LAMBDA_RESPONSE = {
    "StatusCode": 202,
    "ResponseMetadata": {"RequestId": "zztest-request-id", "HTTPStatusCode": 202},
}


@contextmanager
def acting_as(roles, schema="demo"):
    """Run the block inside a request context authenticated as ``roles``."""
    fake_user = MagicMock()
    fake_user.id = 1
    fake_user.config = {"roles": roles}
    fake_user.schema = schema

    with app.test_request_context():
        with (
            patch(
                "decorators.has_permission_decorator.get_jwt_identity", return_value=1
            ),
            patch("decorators.has_permission_decorator.User") as mock_user_cls,
        ):
            mock_user_cls.find.return_value = fake_user
            yield


@contextmanager
def lambda_answering(response=None):
    """Mock the aws module of the service and yield it with a lambda client set up."""
    lambda_client = MagicMock()
    lambda_client.invoke.return_value = (
        LAMBDA_RESPONSE if response is None else response
    )

    with patch.object(admin_drug_service, "aws") as mock_aws:
        mock_aws.get_client.return_value = lambda_client
        yield mock_aws


def _invoke_kwargs(mock_aws) -> dict:
    """The keyword arguments the lambda was invoked with."""
    lambda_client = mock_aws.get_client.return_value
    lambda_client.invoke.assert_called_once()

    return lambda_client.invoke.call_args.kwargs


def test_invokes_the_backend_lambda_asynchronously():
    """The inference runs as a fire-and-forget event on the backend function."""
    with acting_as([Role.CURATOR.value]), lambda_answering() as mock_aws:
        admin_drug_service.predict_substance()

    mock_aws.get_client.assert_called_once_with("lambda", region_name="sa-east-1")

    kwargs = _invoke_kwargs(mock_aws)
    assert kwargs["FunctionName"] == Config.BACKEND_FUNCTION_NAME
    assert kwargs["InvocationType"] == "Event"


def test_payload_names_the_command_and_the_caller_schema():
    """The lambda is told to infer substances for the caller's own schema."""
    with (
        acting_as([Role.CURATOR.value], schema="zztest_hospital"),
        lambda_answering() as mock_aws,
    ):
        admin_drug_service.predict_substance()

    payload = json.loads(_invoke_kwargs(mock_aws)["Payload"])
    assert payload == {"command": INFER_COMMAND, "schema": "zztest_hospital"}


def test_returns_the_request_id_and_status_code():
    """The AWS request id is handed back so the job can be followed."""
    with acting_as([Role.CURATOR.value]), lambda_answering():
        result = admin_drug_service.predict_substance()

    assert result == {"request_id": "zztest-request-id", "status_code": 202}


def test_tolerates_a_response_without_metadata():
    """A response missing metadata and status answers with nulls instead of failing."""
    with acting_as([Role.CURATOR.value]), lambda_answering(response={}):
        result = admin_drug_service.predict_substance()

    assert result == {"request_id": None, "status_code": None}


@pytest.mark.parametrize("role", [Role.ADMIN.value, Role.CURATOR.value])
def test_roles_holding_admin_drugs_can_fire_it(role):
    """ADMIN and CURATOR both carry ADMIN_DRUGS."""
    with acting_as([role]), lambda_answering() as mock_aws:
        admin_drug_service.predict_substance()

    mock_aws.get_client.return_value.invoke.assert_called_once()


@pytest.mark.parametrize(
    "role", [Role.PRESCRIPTION_ANALYST.value, Role.CONFIG_MANAGER.value]
)
def test_requires_admin_drugs(role):
    """A role without ADMIN_DRUGS is refused before the lambda is reached."""
    with acting_as([role]), lambda_answering() as mock_aws:
        with pytest.raises(AuthorizationError):
            admin_drug_service.predict_substance()

    mock_aws.get_client.assert_not_called()
