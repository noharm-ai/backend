"""Integration tests for the Lambda half of the outlier score pipeline.

``tests/integration/test_outlier_generate.py`` covers the drug-scoped
preparation steps and states that it leaves out the entry point that hands
work to AWS Lambda. That entry point is tested here:

* ``POST /outliers/generate/single/<segment>/<drug>``
  (``outlier_service.generate``) — copies the drug's outlier rows out of
  PostgreSQL as CSV, asks the scores Lambda to score them synchronously and
  writes the returned score and count back onto each row.

The Lambda is never contacted: ``aws.get_client`` is replaced by a double
that records the payload it was handed and answers with the response shape
the service parses (a JSON string holding a JSON document).

Everything else runs for real against the database. Ids stay in the reserved
``>= 90000`` range so ``clean_test_artifacts`` removes them.
"""

import io
import json

import pytest
from sqlalchemy import text

from models.main import Outlier
from tests.conftest import session, session_commit
from tests.utils.utils_test_unit_conversion import (
    create_test_drug,
    create_test_substance,
)
from utils import status

_SINGLE_URL = "/outliers/generate/single"
_FOLD_URL = "/outliers/generate/fold"

# seed segment used by the drug-scoped test: only the test drug's outliers are
# read or written there
_SEGMENT_SEED = 1

# ids reserved for this module (>= 90000, distinct from other modules' ranges)
_DRUG_SCORED = 90410  # two outliers in the seed segment, scored by the Lambda
_DRUG_UNSCORED = 90411  # no outliers at all

_OUTLIER_LOW = 90410
_OUTLIER_HIGH = 90411

# (dose, frequency, count) of the two outliers the Lambda scores
_LOW = (100.0, 1.0, 10)
_HIGH = (200.0, 2.0, 4)


def _lambda_double(payload=None):
    """A boto3 lambda client double answering the shape the service parses."""

    class _Double:
        def __init__(self):
            self.calls = []

        def invoke(self, **kwargs):
            self.calls.append(kwargs)
            response = {
                "ResponseMetadata": {"RequestId": "zztest-request-id"},
                "StatusCode": 200,
            }
            if payload is not None:
                # the scores Lambda answers with a JSON string holding a
                # JSON document, so the service json.loads() it twice
                response["Payload"] = io.BytesIO(
                    json.dumps(json.dumps(payload)).encode("utf-8")
                )
            return response

    return _Double()


def _sent_payload(lambda_client):
    """The payload of the single invocation the double recorded."""
    assert len(lambda_client.calls) == 1

    return json.loads(lambda_client.calls[0]["Payload"])


def _create_outlier(id_outlier: int, id_drug: int, id_segment: int, row: tuple):
    """Insert one outlier row with a known dose/frequency/count and no score."""
    dose, frequency, count = row

    outlier = Outlier()
    outlier.id = id_outlier
    outlier.idDrug = id_drug
    outlier.idSegment = id_segment
    outlier.dose = dose
    outlier.frequency = frequency
    outlier.countNum = count
    outlier.score = None

    session.add(outlier)
    session_commit()

    return outlier


def _outliers(id_segment: int, id_drug: int = None):
    """(dose, frequency, count, score) of a segment's outliers, by dose."""
    query = (
        "SELECT doseconv, frequenciadia, contagem, escore FROM demo.outlier "
        "WHERE idsegmento = :id_segment"
    )
    params = {"id_segment": id_segment}

    if id_drug is not None:
        query += " AND fkmedicamento = :id_drug"
        params["id_drug"] = id_drug

    rows = session.execute(text(query + " ORDER BY doseconv"), params).fetchall()

    return [tuple(row) for row in rows]


def _drop_drug(id_drug: int):
    """Remove a drug and everything the pipeline may have attached to it."""
    for query in (
        "DELETE FROM demo.outlier WHERE fkmedicamento = :id",
        "DELETE FROM demo.prescricaoagg WHERE fkmedicamento = :id",
        "DELETE FROM demo.medatributos_audit WHERE fkmedicamento = :id",
        "DELETE FROM demo.medatributos WHERE fkmedicamento = :id",
        "DELETE FROM demo.medicamento WHERE fkmedicamento = :id",
        "DELETE FROM public.substancia WHERE sctid = :id",
    ):
        session.execute(text(query), {"id": id_drug})

    session_commit()


@pytest.fixture
def drug_with_outliers():
    """A drug with two unscored outliers in the seed segment."""
    _drop_drug(_DRUG_SCORED)
    create_test_substance(id=_DRUG_SCORED, name="ZZTEST Substancia Escore")
    create_test_drug(
        id=_DRUG_SCORED, name="ZZTEST Medicamento Escore", sctid=_DRUG_SCORED
    )
    _create_outlier(_OUTLIER_LOW, _DRUG_SCORED, _SEGMENT_SEED, _LOW)
    _create_outlier(_OUTLIER_HIGH, _DRUG_SCORED, _SEGMENT_SEED, _HIGH)

    yield

    _drop_drug(_DRUG_SCORED)


class TestGenerateDrugScores:
    """POST /outliers/generate/single/<segment>/<drug>"""

    def test_the_outlier_rows_are_handed_over_as_csv(
        self, client, admin_headers, monkeypatch, drug_with_outliers
    ):
        """The drug's dose/frequency pairs travel to the Lambda as a CSV [200]"""
        lambda_client = _lambda_double(
            payload={
                str(_DRUG_SCORED): [
                    {"dose": 100.0, "frequency": 1.0, "score": 1, "count": 10},
                    {"dose": 200.0, "frequency": 2.0, "score": 2, "count": 4},
                ]
            }
        )
        monkeypatch.setattr(
            "services.outlier_service.aws.get_client", lambda *a, **k: lambda_client
        )

        response = client.post(
            f"{_SINGLE_URL}/{_SEGMENT_SEED}/{_DRUG_SCORED}", headers=admin_headers
        )

        assert response.status_code == status.HTTP_200_OK

        payload = _sent_payload(lambda_client)
        assert payload["command"] == "lambda_scores.generate_scores"

        lines = payload["csv_string"].strip().split("\n")
        assert lines[0].strip() == "medication,dose,frequency,count"
        assert sorted(line.strip() for line in lines[1:]) == [
            f"{_DRUG_SCORED},100,1,10",
            f"{_DRUG_SCORED},200,2,4",
        ]
        # the scores are needed right away
        assert lambda_client.calls[0]["InvocationType"] == "RequestResponse"

    def test_the_returned_scores_are_written_back(
        self, client, admin_headers, monkeypatch, drug_with_outliers
    ):
        """Each outlier takes the score and count the Lambda computed [200]"""
        lambda_client = _lambda_double(
            payload={
                str(_DRUG_SCORED): [
                    {"dose": 100.0, "frequency": 1.0, "score": 3, "count": 42},
                    {"dose": 200.0, "frequency": 2.0, "score": 7, "count": 8},
                ]
            }
        )
        monkeypatch.setattr(
            "services.outlier_service.aws.get_client", lambda *a, **k: lambda_client
        )

        response = client.post(
            f"{_SINGLE_URL}/{_SEGMENT_SEED}/{_DRUG_SCORED}", headers=admin_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert _outliers(_SEGMENT_SEED, _DRUG_SCORED) == [
            (100.0, 1.0, 42, 3),
            (200.0, 2.0, 8, 7),
        ]

    def test_a_drug_without_outliers_never_reaches_the_lambda(
        self, client, admin_headers, monkeypatch
    ):
        """An empty CSV is only a header line, so there is nothing to score [200]"""
        lambda_client = _lambda_double()
        monkeypatch.setattr(
            "services.outlier_service.aws.get_client", lambda *a, **k: lambda_client
        )

        response = client.post(
            f"{_SINGLE_URL}/{_SEGMENT_SEED}/{_DRUG_UNSCORED}", headers=admin_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert lambda_client.calls == []

    def test_a_lambda_error_leaves_the_outliers_untouched(
        self, client, admin_headers, monkeypatch, drug_with_outliers
    ):
        """A failed score run is reported instead of writing partial data [500]"""
        lambda_client = _lambda_double(
            payload={"error": "scores failed", "requestId": "zztest-failed-request"}
        )
        monkeypatch.setattr(
            "services.outlier_service.aws.get_client", lambda *a, **k: lambda_client
        )

        response = client.post(
            f"{_SINGLE_URL}/{_SEGMENT_SEED}/{_DRUG_SCORED}", headers=admin_headers
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert _outliers(_SEGMENT_SEED, _DRUG_SCORED) == [
            (100.0, 1.0, 10, None),
            (200.0, 2.0, 4, None),
        ]

    def test_the_fold_format_is_discontinued(self, client, admin_headers, monkeypatch):
        """The old per-fold route is refused before anything else happens [500]"""
        lambda_client = _lambda_double()
        monkeypatch.setattr(
            "services.outlier_service.aws.get_client", lambda *a, **k: lambda_client
        )

        response = client.post(f"{_FOLD_URL}/{_SEGMENT_SEED}/1", headers=admin_headers)

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert lambda_client.calls == []

    def test_generating_scores_requires_a_score_permission(
        self, client, analyst_headers, monkeypatch, drug_with_outliers
    ):
        """Scoring is a curation action, closed to the analyst role [401]"""
        lambda_client = _lambda_double()
        monkeypatch.setattr(
            "services.outlier_service.aws.get_client", lambda *a, **k: lambda_client
        )

        response = client.post(
            f"{_SINGLE_URL}/{_SEGMENT_SEED}/{_DRUG_SCORED}", headers=analyst_headers
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert lambda_client.calls == []
