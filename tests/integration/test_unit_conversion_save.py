"""Integration tests for the write half of the drug unit-conversion feature.

``GET /drugs/unit-conversion/<drug>`` is covered by
``tests/unit/test_unit_conversion_service.py``; this module covers the two
endpoints that change data:

* ``POST /drugs/unit-conversion/<drug>`` — the curator screen that fixes a
  drug's conversion factors. The backend validates the payload and hands it to
  backend-private (``lambda_unit_conversion.save_drug_conversions``), which
  applies it to *every* segment: it upserts the ``unidadeconverte`` rows, pins
  the substance's default unit (``un`` as fallback) on each ``medatributos``
  row, creating rows and the ``unidademedida`` entry where missing, and
  recalculates the max dose. Those effects are tested in backend-private; here
  the Lambda is stubbed and the tests assert the payload and how the answer is
  handled.
* ``POST /drugs/process-scores/<drug>`` — hands the drug to the score Lambda.

Fixtures use the reserved ``>= 90000`` id range (90400 block) so the
session-scoped ``clean_test_artifacts`` fixture removes them.
"""

import io
import json
from unittest.mock import MagicMock, patch

import pytest

from models.appendix import MeasureUnitConvert
from models.segment import Segment
from tests.conftest import session, session_commit
from tests.utils.utils_test_unit_conversion import (
    create_test_drug,
    create_test_substance,
)
from utils import status

SAVE_URL = "/drugs/unit-conversion"
SCORES_URL = "/drugs/process-scores"

# Ids reserved for this module (90400 block, distinct from other modules').
_SCTID = 90401

_DRUG_SAVED = 90401  # handed to backend-private
_DRUG_SCORES = 90407  # target of the score endpoint
_DRUG_REJECTED = 90408  # receives the payloads that must be refused
_UNKNOWN_DRUG = 90499

# an existing seed unit, used as the converted-from unit
_SEED_MEASURE_UNIT = "1"

# the demo user behind the config_manager_headers fixture
CALLER_ID = 1
CALLER_SCHEMA = "demo"


@pytest.fixture(scope="module", autouse=True)
def setup_unit_conversion_data(clean_test_artifacts):  # noqa: ARG001
    """Create the substance and drugs for this module, after the global cleanup."""
    create_test_substance(_SCTID, "ZZTest Substância Unidade", "mg")

    for id_drug, name in [
        (_DRUG_SAVED, "ZZTest Medicamento Conversao"),
        (_DRUG_SCORES, "ZZTest Medicamento Escores"),
        (_DRUG_REJECTED, "ZZTest Medicamento Recusado"),
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


def _save(client, headers, id_drug, conversion_list, lambda_client=None):
    """POST a conversion list, with backend-private stubbed so nothing leaves the process."""
    lambda_client = lambda_client or _backend_private({"success": True})

    with patch(
        "utils.lambdautils.aws.get_client", return_value=lambda_client
    ) as get_client:
        response = client.post(
            f"{SAVE_URL}/{id_drug}",
            data=json.dumps({"conversion_list": conversion_list}),
            headers=headers,
        )

    return response, get_client


def _conversions(id_drug: int) -> dict:
    """Saved factors for a drug, keyed by (segment, measure unit)."""
    session_commit()  # see the rows the request committed

    rows = (
        session.query(MeasureUnitConvert)
        .filter(MeasureUnitConvert.idDrug == id_drug)
        .all()
    )

    return {(r.idSegment, r.idMeasureUnit): r.factor for r in rows}


def test_save_hands_the_conversions_to_backend_private(
    client, config_manager_headers
):
    """One payload, no segment in it; backend-private applies it to every segment [200]."""
    lambda_client = _backend_private({"success": True})

    response, _ = _save(
        client,
        config_manager_headers,
        _DRUG_SAVED,
        [
            {"id_measure_unit": "mg", "factor": 1},
            {"id_measure_unit": _SEED_MEASURE_UNIT, "factor": 0.5},
        ],
        lambda_client,
    )

    assert response.status_code == status.HTTP_200_OK

    kwargs = lambda_client.invoke.call_args.kwargs
    # synchronous, so a failed save is reported to the curator
    assert kwargs["InvocationType"] == "RequestResponse"
    assert json.loads(kwargs["Payload"]) == {
        "command": "lambda_unit_conversion.save_drug_conversions",
        "schema": CALLER_SCHEMA,
        "id_drug": _DRUG_SAVED,
        "id_user": CALLER_ID,
        "units": [
            {"id_measure_unit": "mg", "factor": 1},
            {"id_measure_unit": _SEED_MEASURE_UNIT, "factor": 0.5},
        ],
        # the client asks for the scores in a separate request
        "process_scores": False,
    }

    # the service reads the segments without an ORDER BY, so only the set of
    # names it reports is part of the contract
    assert sorted(response.get_json()["data"]["updated"]) == sorted(
        s.description for s in session.query(Segment).all()
    )


@pytest.mark.parametrize(
    "lambda_response, function_error",
    [
        # the command raised: backend-private answers a JSON-encoded error string
        (json.dumps({"error": True, "message": "drug not found"}), False),
        # the lambda itself crashed or timed out
        ({"errorMessage": "Task timed out"}, True),
    ],
    ids=["command error", "function error"],
)
def test_save_reports_a_backend_private_failure(
    client, config_manager_headers, lambda_response, function_error
):
    """A failed backend-private call is not reported as saved [500]."""
    response, _ = _save(
        client,
        config_manager_headers,
        _DRUG_SAVED,
        [{"id_measure_unit": _SEED_MEASURE_UNIT, "factor": 1}],
        _backend_private(lambda_response, function_error=function_error),
    )

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.get_json()["code"] == "errors.businessRules"


@pytest.mark.parametrize(
    "conversion_list",
    [
        [],
        [{"id_measure_unit": _SEED_MEASURE_UNIT, "factor": 0}],
        [{"id_measure_unit": _SEED_MEASURE_UNIT, "factor": -2}],
    ],
    ids=["empty list", "zero factor", "negative factor"],
)
def test_save_rejects_a_conversion_list_it_cannot_apply(
    client, config_manager_headers, conversion_list
):
    """A missing list or a non-positive factor would silently break dose conversion [400]."""
    response, get_client = _save(
        client, config_manager_headers, _DRUG_REJECTED, conversion_list
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidParams"
    get_client.assert_not_called()
    assert _conversions(_DRUG_REJECTED) == {}


def test_save_rejects_a_non_numeric_factor(client, config_manager_headers):
    """The factor is typed, so a text value never reaches the service [400]."""
    response, get_client = _save(
        client,
        config_manager_headers,
        _DRUG_REJECTED,
        [{"id_measure_unit": _SEED_MEASURE_UNIT, "factor": "muito"}],
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["validations"]
    get_client.assert_not_called()


def test_save_rejects_an_unknown_drug(client, config_manager_headers):
    """There is no drug to convert, so backend-private is not called [400]."""
    response, get_client = _save(
        client,
        config_manager_headers,
        _UNKNOWN_DRUG,
        [{"id_measure_unit": _SEED_MEASURE_UNIT, "factor": 1}],
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidRecord"
    get_client.assert_not_called()


def test_role_without_write_drug_attributes_cannot_save(client, analyst_headers):
    """PRESCRIPTION_ANALYST may read conversions but never write them [401]."""
    response, get_client = _save(
        client,
        analyst_headers,
        _DRUG_REJECTED,
        [{"id_measure_unit": _SEED_MEASURE_UNIT, "factor": 1}],
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    get_client.assert_not_called()


def test_process_scores_hands_the_drug_to_the_lambda(client, config_manager_headers):
    """The score request carries the caller's schema and user, not just the drug [200]."""
    lambda_client = MagicMock()
    lambda_client.invoke.return_value = {
        "ResponseMetadata": {"RequestId": "zztest-request-id"},
        "StatusCode": 202,
    }

    with patch(
        "services.unit_conversion_service.aws.get_client", return_value=lambda_client
    ):
        response = client.post(
            f"{SCORES_URL}/{_DRUG_SCORES}", headers=config_manager_headers
        )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == {
        "request_id": "zztest-request-id",
        "status_code": 202,
    }

    payload = json.loads(lambda_client.invoke.call_args.kwargs["Payload"])
    assert payload == {
        "command": "lambda_scores.process_drug_scores",
        "schema": CALLER_SCHEMA,
        "id_user": CALLER_ID,
        "id_drug": _DRUG_SCORES,
    }
    # fire and forget: the caller polls the scores, it does not wait here
    assert lambda_client.invoke.call_args.kwargs["InvocationType"] == "Event"


def test_process_scores_requires_write_drug_attributes(client, analyst_headers):
    """Regenerating scores is a curation action, closed to the analyst role [401]."""
    with patch("services.unit_conversion_service.aws.get_client") as get_client:
        response = client.post(f"{SCORES_URL}/{_DRUG_SCORES}", headers=analyst_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    get_client.assert_not_called()
