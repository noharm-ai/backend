"""Integration tests for the navigation "discharge summary" endpoint.

Covers ``navigation_service.create_discharge_summary``
(POST /navigation/discharge-summary), which sends the discharge summary of an
admission that was *already* copied to a navigation schema — no patient and no
prescription are created on this path.

Only the Lambda call is mocked; the encryption and the error handling run for
real. The payload the service would have sent is captured from the mock and
decrypted, so the tests assert on what actually crosses the boundary.
"""

import base64
import io
import json
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from config import Config
from security.role import Role
from tests.conftest import get_access, make_headers

URL = "/navigation/discharge-summary"

ADMISSION = 991001


@pytest.fixture
def fernet(monkeypatch):
    """Install a throwaway ENCRYPTION_KEY and return the matching Fernet."""
    key = Fernet.generate_key()
    monkeypatch.setattr(Config, "ENCRYPTION_KEY", key.decode("utf-8"))
    return Fernet(key)


@pytest.fixture
def lambda_client():
    """Patch the boto3 Lambda client and return the MagicMock standing in for it.

    ``utils.aws.get_client`` is memoised, so the module attribute is patched
    rather than the boto3 factory underneath it.
    """
    client = MagicMock()
    client.invoke.return_value = _lambda_response(
        {"success": True, "data": {"to_admission_number": 1991001}}
    )

    with patch("services.navigation_service.aws.get_client", return_value=client):
        yield client


def _lambda_response(payload):
    """Wrap a dict the way boto3 returns a Lambda RequestResponse invocation."""
    return {"Payload": io.BytesIO(json.dumps(payload).encode("utf-8"))}


def _body(admission_number=ADMISSION, notes=None):
    """Build a valid request body for the discharge summary endpoint."""
    return {
        "admission_number": admission_number,
        "clinical_notes": {"admission": "zztest note"} if notes is None else notes,
    }


def _sent_payload(lambda_client):
    """Decode the JSON payload handed to the Lambda invocation."""
    assert lambda_client.invoke.call_count == 1
    return json.loads(lambda_client.invoke.call_args.kwargs["Payload"])


def _decrypt(fernet, value):
    """Reverse ``cryptutils.encrypt_data`` for an encrypted payload field."""
    return fernet.decrypt(base64.b64decode(value)).decode("utf-8")


# --- guards ----------------------------------------------------------------


def test_discharge_summary_requires_the_nav_permission(client):
    """An analyst has no NAV_COPY_PATIENT permission, so the send is refused."""
    headers = make_headers(get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value]))

    response = client.post(URL, json=_body(), headers=headers)

    assert response.status_code == 401


def test_discharge_summary_rejects_an_incomplete_body(client, navigator_headers):
    """Every NavCreateDischargeSummaryRequest field is required [400]."""
    response = client.post(
        URL, json={"admission_number": ADMISSION}, headers=navigator_headers
    )

    assert response.status_code == 400


# --- happy path ------------------------------------------------------------


def test_discharge_summary_returns_the_lambda_response(
    client, navigator_headers, fernet, lambda_client
):
    """The Lambda payload — including the navigation admission number — is
    returned to the caller untouched."""
    lambda_client.invoke.return_value = _lambda_response(
        {"success": True, "data": {"to_admission_number": 1991001}}
    )

    response = client.post(URL, json=_body(), headers=navigator_headers)

    assert response.status_code == 200
    assert response.get_json()["data"] == {
        "success": True,
        "data": {"to_admission_number": 1991001},
    }


def test_discharge_summary_sends_the_admission_context_to_the_lambda(
    client, navigator_headers, fernet, lambda_client
):
    """The payload names the command, both schemas and the origin admission."""
    client.post(URL, json=_body(), headers=navigator_headers)

    payload = _sent_payload(lambda_client)

    assert payload["command"] == "lambda_navigation.create_discharge_summary"
    assert payload["from_schema"] == "demo"
    assert payload["to_schema"] == "demo"
    assert payload["from_admission_number"] == ADMISSION
    assert payload["encrypted"] is True


def test_discharge_summary_copies_no_patient_data(
    client, navigator_headers, fernet, lambda_client
):
    """No patient is created here, so no identity or drug data is sent."""
    client.post(URL, json=_body(), headers=navigator_headers)

    payload = _sent_payload(lambda_client)

    assert "patient_name" not in payload
    assert "patient_phone" not in payload
    assert "drug_list" not in payload


# --- encryption ------------------------------------------------------------


def test_discharge_summary_encrypts_every_clinical_note(
    client, navigator_headers, fernet, lambda_client
):
    """Each clinical note value is encrypted before it leaves the API."""
    notes = {"admission": "zztest admission note", "recipe": "zztest recipe"}

    client.post(URL, json=_body(notes=notes), headers=navigator_headers)

    encrypted = _sent_payload(lambda_client)["clinical_notes"]

    assert set(encrypted.keys()) == set(notes.keys())
    for key, value in notes.items():
        assert encrypted[key] != value
        assert _decrypt(fernet, encrypted[key]) == value


# --- lambda failure --------------------------------------------------------


def test_discharge_summary_reports_a_patient_missing_from_navigation(
    client, navigator_headers, fernet, lambda_client
):
    """ADMISSION_NOT_FOUND is the "copy the patient first" case [400].

    It comes back as a *successful* invocation carrying ``success: false``, so
    it has to be recognised by its error code rather than by an "error" key.
    """
    lambda_client.invoke.return_value = _lambda_response(
        {
            "success": False,
            "error_code": "ADMISSION_NOT_FOUND",
            "message": "Admission 1991001 not found in schema demo",
        }
    )

    response = client.post(URL, json=_body(), headers=navigator_headers)

    assert response.status_code == 400
    assert "ainda não foi copiado para a navegação" in response.get_json()["message"]


def test_discharge_summary_reports_a_lambda_failure_as_a_server_error(
    client, navigator_headers, fernet, lambda_client
):
    """The shared lambda decorator returns a JSON *string* on generic failures.

    ``lambdautils.response_to_json`` unwraps the double encoding; the "error"
    key then surfaces as a 500 with a generic message.
    """
    lambda_client.invoke.return_value = _lambda_response(
        json.dumps(
            {
                "error": True,
                "requestId": "zztest-request-id",
                "message": "zztest lambda failure",
            }
        )
    )

    response = client.post(URL, json=_body(), headers=navigator_headers)

    assert response.status_code == 500
    assert "Ocorreu um erro ao enviar" in response.get_json()["message"]
