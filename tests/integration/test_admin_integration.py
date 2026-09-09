"""Tests: POST /admin/integration/update-user-security-group

Support tooling: it opens the client's AWS security group for the machine the
caller is asking from, so an operator can reach the integration environment.
The backend itself changes nothing -- a Lambda does -- and everything worth
pinning down is what the backend decides around that call:

* only a role holding UPDATE_USER_SG may ask (the route is also refused
  outright in production, which ``api_endpoint(is_admin=True)`` handles and
  ``tests/unit/test_api_endpoint_decorator.py`` covers);
* the rule is opened for the *caller's* address, taken from the proxy headers
  the way the API Gateway forwards it, narrowed to a single host (``/32``);
* the Lambda answer is handed back untouched, including when it arrives
  double-encoded (a JSON string holding JSON), which is how the function
  replies today;
* an answer flagged ``error`` becomes a business-rule error, and then nothing
  is audited;
* a successful change leaves an audit record naming the schema, the new
  address and who asked.

The Lambda is replaced by a recorder throughout: the test asserts on the
payload the backend sends, which is the part it actually decides.
"""

import io
import json

import pytest
from sqlalchemy import text

from config import Config
from models.enums import SchemaConfigAuditTypeEnum
from services.admin import admin_integration_service
from tests.conftest import session, session_commit
from utils import status

URL = "/admin/integration/update-user-security-group"

# public.usuario row behind the admin_headers fixture
_ADMIN_USER_ID = 2
_ADMIN_USER_EMAIL = "user@admin.com"
_ADMIN_USER_SCHEMA = "demo"

# the command the backend Lambda dispatches on
_COMMAND = "lambda_create_schema.update_user_sec_group_rules"

# a documentation address (RFC 5737), forwarded as if by the API Gateway
_CALLER_IP = "203.0.113.7"

# what the test client itself connects from, when no proxy header is present
_CONNECTION_IP = "127.0.0.1"

_AUDIT_TYPE = SchemaConfigAuditTypeEnum.USER_SECURITY_GROUP.value


class _FakeLambda:
    """Records every invoke and replies with what the test asked for."""

    def __init__(self):
        self.clients = []
        self.invocations = []
        self.reply = {"status": "ok"}

    def get_client(self, service_name: str, region_name: str = None):
        """Stands in for ``utils.aws.get_client``."""
        self.clients.append((service_name, region_name))
        return self

    def invoke(self, **kwargs):
        """Stands in for the boto3 Lambda client."""
        self.invocations.append(kwargs)

        body = self.reply
        if not isinstance(body, str):
            body = json.dumps(body)

        return {"Payload": io.BytesIO(body.encode("utf-8"))}

    @property
    def payload(self):
        """The payload of the single invocation the endpoint made."""
        assert len(self.invocations) == 1
        return json.loads(self.invocations[0]["Payload"])


@pytest.fixture
def aws_lambda(monkeypatch):
    """Replace the AWS layer of the service with a recorder."""
    fake = _FakeLambda()
    monkeypatch.setattr(admin_integration_service.aws, "get_client", fake.get_client)

    return fake


@pytest.fixture(autouse=True)
def clean_audit():
    """The seed dump has no audit record of this kind: keep it that way."""
    _remove_audit()
    yield
    _remove_audit()


def _remove_audit():
    """Drop the audit records this endpoint writes."""
    session.execute(
        text("DELETE FROM public.schema_config_audit WHERE tp_audit = :type"),
        {"type": _AUDIT_TYPE},
    )
    session_commit()


def _audit_records():
    """Every security-group audit record, oldest first."""
    return session.execute(
        text(
            "SELECT schema_name, tp_audit, extra, created_by "
            "FROM public.schema_config_audit "
            "WHERE tp_audit = :type ORDER BY idschema_config_audit"
        ),
        {"type": _AUDIT_TYPE},
    ).all()


def _call(client, headers, caller_ip=_CALLER_IP):
    """Ask for the caller's address to be allowed."""
    if caller_ip is not None:
        headers = {**headers, "X-Forwarded-For": caller_ip}

    return client.post(URL, headers=headers)


def test_update_requires_the_update_user_sg_permission(
    client, analyst_headers, aws_lambda
):
    """POST /admin/integration/update-user-security-group - a role without UPDATE_USER_SG is refused [401 UNAUTHORIZED]"""
    response = _call(client, analyst_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    # the Lambda must not have been reached at all
    assert aws_lambda.invocations == []
    assert _audit_records() == []


def test_update_invokes_the_backend_lambda_synchronously(
    client, admin_headers, aws_lambda
):
    """POST /admin/integration/update-user-security-group - the backend function is invoked once, synchronously"""
    response = _call(client, admin_headers)

    assert response.status_code == status.HTTP_200_OK
    assert aws_lambda.clients == [("lambda", Config.NIFI_SQS_QUEUE_REGION)]
    assert len(aws_lambda.invocations) == 1
    assert aws_lambda.invocations[0]["FunctionName"] == Config.BACKEND_FUNCTION_NAME
    assert aws_lambda.invocations[0]["InvocationType"] == "RequestResponse"


def test_update_asks_for_the_caller_address_as_a_single_host_rule(
    client, admin_headers, aws_lambda
):
    """POST /admin/integration/update-user-security-group - the forwarded caller address is opened as a /32"""
    _call(client, admin_headers)

    assert aws_lambda.payload == {
        "command": _COMMAND,
        "user": _ADMIN_USER_EMAIL,
        "new_cidr": f"{_CALLER_IP}/32",
    }


def test_update_falls_back_to_the_connection_address(client, admin_headers, aws_lambda):
    """POST /admin/integration/update-user-security-group - without a proxy header the connection address is used"""
    _call(client, admin_headers, caller_ip=None)

    assert aws_lambda.payload["new_cidr"] == f"{_CONNECTION_IP}/32"


def test_update_uses_the_first_forwarded_address(client, admin_headers, aws_lambda):
    """POST /admin/integration/update-user-security-group - the original client wins over the proxies behind it"""
    _call(client, admin_headers, caller_ip=f"{_CALLER_IP}, 198.51.100.4")

    assert aws_lambda.payload["new_cidr"] == f"{_CALLER_IP}/32"


def test_update_returns_the_lambda_answer(client, admin_headers, aws_lambda):
    """POST /admin/integration/update-user-security-group - the Lambda answer is handed back untouched"""
    aws_lambda.reply = {"error": False, "message": "grupo atualizado"}

    response = _call(client, admin_headers)

    assert response.status_code == status.HTTP_200_OK
    assert json.loads(response.data)["data"] == {
        "error": False,
        "message": "grupo atualizado",
    }


def test_update_unwraps_a_double_encoded_answer(client, admin_headers, aws_lambda):
    """POST /admin/integration/update-user-security-group - an answer encoded as a JSON string is decoded twice"""
    aws_lambda.reply = json.dumps({"status": "ok", "rules": 2})

    response = _call(client, admin_headers)

    assert response.status_code == status.HTTP_200_OK
    assert json.loads(response.data)["data"] == {"status": "ok", "rules": 2}


def test_update_audits_the_new_address(client, admin_headers, aws_lambda):
    """POST /admin/integration/update-user-security-group - the change is audited with the schema, address and author"""
    _call(client, admin_headers)

    records = _audit_records()

    assert len(records) == 1
    schema_name, audit_type, extra, created_by = records[0]
    assert schema_name == _ADMIN_USER_SCHEMA
    assert audit_type == _AUDIT_TYPE
    assert extra == {"new_user_ip": _CALLER_IP}
    assert created_by == _ADMIN_USER_ID


def test_update_reports_a_lambda_error_as_a_business_rule_error(
    client, admin_headers, aws_lambda
):
    """POST /admin/integration/update-user-security-group - an answer flagged error is reported to the caller [400 BAD REQUEST]"""
    aws_lambda.reply = {"error": True, "message": "limite de regras atingido"}

    response = _call(client, admin_headers)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    body = json.loads(response.data)
    assert body["message"] == "limite de regras atingido"
    assert body["code"] == "errors.businessRules"


def test_update_does_not_audit_a_failed_change(client, admin_headers, aws_lambda):
    """POST /admin/integration/update-user-security-group - a refused change leaves no audit record"""
    aws_lambda.reply = {"error": True, "message": "limite de regras atingido"}

    _call(client, admin_headers)

    assert _audit_records() == []


def test_update_reports_a_default_message_for_a_mute_error(
    client, admin_headers, aws_lambda
):
    """POST /admin/integration/update-user-security-group - an error without a message still says something [400 BAD REQUEST]"""
    aws_lambda.reply = {"error": True}

    response = _call(client, admin_headers)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert json.loads(response.data)["message"] == ("Erro inesperado. Consulte os logs")
