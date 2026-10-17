"""Integration tests for the drug score-generation config endpoint.

Before a drug can be scored, a curator sets how its doses are read: the
division range and whether the dose is per kilo. That is what
``POST /outliers/generate/config/<segment>/<drug>/v2`` does, as the first step
of the "generate score" drawer (the client runs ``prepare`` and ``single``
afterwards).

The backend only validates the request and hands it to backend-private
(``lambda_scores.set_division_range``), which creates the ``medatributos`` row
from the substance when missing, stores ``divisor``/``usapeso`` and recalculates
the max dose. Those effects are tested in backend-private; here the Lambda is
stubbed and the tests assert the guards, the payload and how the answer is
handled.

Fixtures use the reserved ``>= 90000`` id range (91100 block) so the
session-scoped ``clean_test_artifacts`` fixture removes them.
"""

import io
import json
from unittest.mock import MagicMock, patch

import pytest

from models.main import DrugAttributes
from tests.conftest import session, session_commit
from tests.utils.utils_test_unit_conversion import (
    create_test_drug,
    create_test_substance,
)
from utils import status

CONFIG_URL = "/outliers/generate/config"

_SEGMENT = 1
# the demo user is authorized on segments 1 and 2 only
_UNAUTHORIZED_SEGMENT = 3

# the demo user behind the config_manager_headers fixture
CALLER_ID = 1
CALLER_SCHEMA = "demo"

# Ids reserved for this module (91100 block, distinct from other modules').
_SCTID = 91101

_DRUG = 91101  # handed to backend-private
_DRUG_REJECTED = 91111  # receives the payloads that must be refused
_UNKNOWN_DRUG = 91199


@pytest.fixture(scope="module", autouse=True)
def setup_score_config_data(clean_test_artifacts):  # noqa: ARG001
    """Create the substance and drugs for this module, after the global cleanup."""
    create_test_substance(_SCTID, "ZZTest Substância Config", "mg")

    for id_drug, name in [
        (_DRUG, "ZZTest Medicamento Config"),
        (_DRUG_REJECTED, "ZZTest Medicamento Config Recusado"),
    ]:
        create_test_drug(id_drug, name, _SCTID)


def _backend_private(response, function_error=False):
    """Lambda client double answering ``response`` as backend-private would."""
    lambda_client = MagicMock()

    def invoke(**kwargs):
        result = {"Payload": io.BytesIO(json.dumps(response).encode("utf-8"))}
        if function_error:
            result["FunctionError"] = "Unhandled"
        return result

    lambda_client.invoke.side_effect = invoke
    return lambda_client


def _config(
    client,
    headers,
    id_drug: int,
    id_segment: int = _SEGMENT,
    lambda_client=None,
    **payload,
):
    """POST the config payload, with backend-private stubbed so nothing leaves the process."""
    lambda_client = lambda_client or _backend_private({"success": True})

    body = {"division": None, "useWeight": False}
    body.update(payload)

    with patch("utils.lambdautils.aws.get_client", return_value=lambda_client):
        response = client.post(
            f"{CONFIG_URL}/{id_segment}/{id_drug}/v2", json=body, headers=headers
        )

    return response, lambda_client


def _sent_payload(lambda_client) -> dict:
    """Return the payload of the single backend-private call."""
    lambda_client.invoke.assert_called_once()
    return json.loads(lambda_client.invoke.call_args.kwargs["Payload"])


# ---------------------------------------------------------------------------
# payload sent to backend-private
# ---------------------------------------------------------------------------


def test_config_hands_the_division_range_to_backend_private(
    client, config_manager_headers
):
    """POST config/v2 - one synchronous call, without score generation [200]"""
    response, lambda_client = _config(
        client, config_manager_headers, _DRUG, division=4, useWeight=True
    )

    assert response.status_code == status.HTTP_200_OK

    # synchronous, so a failed save is reported to the curator
    assert lambda_client.invoke.call_args.kwargs["InvocationType"] == "RequestResponse"
    assert _sent_payload(lambda_client) == {
        "command": "lambda_scores.set_division_range",
        "schema": CALLER_SCHEMA,
        "id_drug": _DRUG,
        "id_segment": _SEGMENT,
        "id_user": CALLER_ID,
        "division_range": 4,
        "use_weight": True,
        # the client generates the scores afterwards (prepare + single)
        "process_scores": False,
    }


def test_config_converts_a_division_sent_as_text(client, config_manager_headers):
    """POST config/v2 - the screen keeps the division in a text field, so it
    arrives as a string and is sent to backend-private as a number"""
    response, lambda_client = _config(
        client, config_manager_headers, _DRUG, division="5", useWeight=True
    )

    assert response.status_code == status.HTTP_200_OK

    payload = _sent_payload(lambda_client)
    assert payload["division_range"] == 5.0
    assert isinstance(payload["division_range"], float)


@pytest.mark.parametrize("division", [0, None, "", "0"])
def test_config_sends_no_division_for_no_ranges(
    client, config_manager_headers, division
):
    """POST config/v2 - the screen sends 0 or null for "no ranges", sent as null
    so the score pipeline does not divide by it"""
    response, lambda_client = _config(
        client, config_manager_headers, _DRUG, division=division, useWeight=None
    )

    assert response.status_code == status.HTTP_200_OK

    payload = _sent_payload(lambda_client)
    assert payload["division_range"] is None
    # the screen sends null when there are no ranges; backend-private needs a bool
    assert payload["use_weight"] is False


def test_config_writes_nothing_in_the_request_session(
    client, config_manager_headers
):
    """POST config/v2 - backend-private commits in its own session, so the
    request must not create the medatributos row itself"""
    response, _ = _config(client, config_manager_headers, _DRUG, division=4)

    assert response.status_code == status.HTTP_200_OK

    session_commit()
    assert (
        session.query(DrugAttributes)
        .filter(DrugAttributes.idDrug == _DRUG)
        .filter(DrugAttributes.idSegment == _SEGMENT)
        .first()
        is None
    )


def test_config_reports_a_backend_private_failure(client, config_manager_headers):
    """POST config/v2 - a failed command is reported to the curator
    [500 INTERNAL SERVER ERROR]"""
    response, _ = _config(
        client,
        config_manager_headers,
        _DRUG,
        lambda_client=_backend_private({"error": True, "message": "boom"}),
    )

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.get_json()["code"] == "errors.businessRules"


def test_config_reports_a_lambda_crash(client, config_manager_headers):
    """POST config/v2 - a Lambda that crashed or timed out is reported too
    [500 INTERNAL SERVER ERROR]"""
    response, _ = _config(
        client,
        config_manager_headers,
        _DRUG,
        lambda_client=_backend_private(
            {"errorMessage": "Task timed out"}, function_error=True
        ),
    )

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.get_json()["code"] == "errors.businessRules"


# ---------------------------------------------------------------------------
# payload guards: refused before backend-private is called
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("division", [1, -2, "1", "abc"])
def test_config_rejects_an_invalid_division(client, config_manager_headers, division):
    """POST config/v2 - a divisor of 1 would produce a single range, a negative
    one none at all, and text is not a number [400 BAD REQUEST]"""
    response, lambda_client = _config(
        client, config_manager_headers, _DRUG_REJECTED, division=division
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidParams"
    lambda_client.invoke.assert_not_called()


def test_config_rejects_use_weight_without_a_division(
    client, config_manager_headers
):
    """POST config/v2 - the dose per kilo is only read through ranges
    [400 BAD REQUEST]"""
    response, lambda_client = _config(
        client, config_manager_headers, _DRUG_REJECTED, division=None, useWeight=True
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidParams"
    lambda_client.invoke.assert_not_called()


def test_config_rejects_an_unauthorized_segment(client, config_manager_headers):
    """POST config/v2 - the caller must be authorized on the segment
    [401 UNAUTHORIZED]"""
    response, lambda_client = _config(
        client,
        config_manager_headers,
        _DRUG_REJECTED,
        id_segment=_UNAUTHORIZED_SEGMENT,
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.get_json()["code"] == "errors.businessRules"
    lambda_client.invoke.assert_not_called()


def test_config_rejects_an_unknown_drug(client, config_manager_headers):
    """POST config/v2 - a drug with no medicamento row cannot be configured
    [400 BAD REQUEST]"""
    response, lambda_client = _config(client, config_manager_headers, _UNKNOWN_DRUG)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidRecord"
    lambda_client.invoke.assert_not_called()


def test_config_requires_the_drug_attributes_permission(client, viewer_headers):
    """POST config/v2 - a role without WRITE_DRUG_ATTRIBUTES is refused
    [401 UNAUTHORIZED]"""
    response, lambda_client = _config(client, viewer_headers, _DRUG_REJECTED)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    lambda_client.invoke.assert_not_called()
