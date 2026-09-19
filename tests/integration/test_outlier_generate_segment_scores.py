"""Integration tests for the Lambda half of the outlier score pipeline.

``tests/integration/test_outlier_generate.py`` covers the drug-scoped
preparation steps and states that it leaves out the entry points that hand
work to AWS Lambda. Those are the three tested here, and none of them was
reached by any test:

* ``POST /outliers/generate/single/<segment>/<drug>``
  (``outlier_service.generate``) — copies the drug's outlier rows out of
  PostgreSQL as CSV, asks the scores Lambda to score them synchronously and
  writes the returned score and count back onto each row;
* ``POST /outliers/generate/segment`` (``generate_segment_scores``) — rebuilds
  every outlier of a segment from its aggregated history, back-fills the drug
  attributes the new outliers expose as missing, then fires the scoring
  Lambda and returns its request id for polling;
* ``GET /outliers/generate/refresh-agg`` (``refresh_agg``) — asks the Lambda
  to recalculate ``prescricaoagg``, but only once every frequency has been
  converted.

The Lambda is never contacted: ``aws.get_client`` is replaced by a double
that records the payload it was handed and answers with the response shape
the service parses (for the synchronous call, a JSON string holding a JSON
document).

Everything else runs for real against the database. The segment-wide test
owns a segment of its own (``_SEGMENT_SCORES``) because ``refresh_outliers``
deletes and re-inserts every outlier of the segment it is given, which would
otherwise wipe the seed rows the rest of the suite reads. Ids stay in the
reserved ``>= 90000`` range so ``clean_test_artifacts`` removes them, and the
segment, its department mapping and its aggregated history — which sit outside
that range because ``idsegmento`` is a smallint — are removed by the fixture
itself.
"""

import io
import json

import pytest
from sqlalchemy import text

from models.main import Outlier
from tests.conftest import session, session_commit
from tests.utils.utils_test_unit_conversion import create_test_drug, create_test_substance
from utils import status

_SINGLE_URL = "/outliers/generate/single"
_FOLD_URL = "/outliers/generate/fold"
_SEGMENT_URL = "/outliers/generate/segment"
_REFRESH_AGG_URL = "/outliers/generate/refresh-agg"

_SCHEMA = "demo"

# the caller behind admin_headers, as the payloads carry it
_CALLER_ID = 2

# seed segment used by the drug-scoped test: only the test drug's outliers are
# read or written there
_SEGMENT_SEED = 1
# seed CPOE segment: it has no aggregated history, which is the refusal case
_SEGMENT_WITHOUT_HISTORY = 2

# ids reserved for this module (>= 90000, distinct from other modules' ranges)
_DRUG_SCORED = 90410  # two outliers in the seed segment, scored by the Lambda
_DRUG_UNSCORED = 90411  # no outliers at all
_DRUG_HISTORY = 90420  # aggregated history in the dedicated segment
_DRUG_STALE = 90421  # an outlier with no history behind it

_OUTLIER_LOW = 90410
_OUTLIER_HIGH = 90411
_OUTLIER_STALE = 90421

# segment/department of the dedicated segment: ``idsegmento`` is a smallint,
# so it cannot join the >= 90000 range the drug ids use
_SEGMENT_SCORES = 30400
_DEPARTMENT_SCORES = 30400

# (dose, frequency, count) of the two outliers the Lambda scores
_LOW = (100.0, 1.0, 10)
_HIGH = (200.0, 2.0, 4)

# (dose, frequency, count) of the two aggregated history rows
_HISTORY_LOW = (50.0, 1.0, 5)
_HISTORY_HIGH = (150.0, 2.0, 3)

_PENDING_FREQUENCY = "ZZT-PENDING"


def _lambda_double(payload=None, request_id="zztest-request-id", status_code=200):
    """A boto3 lambda client double answering the shape the service parses."""

    class _Double:
        def __init__(self):
            self.calls = []

        def invoke(self, **kwargs):
            self.calls.append(kwargs)
            response = {
                "ResponseMetadata": {"RequestId": request_id},
                "StatusCode": status_code,
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


def _drop_segment():
    """Remove the dedicated segment, its mapping and everything scored in it."""
    for query in (
        "DELETE FROM demo.outlier WHERE idsegmento = :id",
        "DELETE FROM demo.prescricaoagg WHERE idsegmento = :id",
        "DELETE FROM demo.segmentosetor WHERE idsegmento = :id",
        "DELETE FROM demo.segmento WHERE idsegmento = :id",
    ):
        session.execute(text(query), {"id": _SEGMENT_SCORES})

    session_commit()


@pytest.fixture
def segment_with_history():
    """A segment of its own, with a department mapping and two history rows.

    ``refresh_outliers`` rebuilds a whole segment, so the seed segment cannot
    be used. The aggregated rows go in through a plain INSERT, which fires
    ``trg_complete_prescricaoagg``: it resolves the segment from the
    department, which is why the mapping is created first.
    """
    _drop_drug(_DRUG_HISTORY)
    _drop_segment()
    create_test_substance(id=_DRUG_HISTORY, name="ZZTEST Substancia Historico")
    create_test_drug(
        id=_DRUG_HISTORY, name="ZZTEST Medicamento Historico", sctid=_DRUG_HISTORY
    )

    session.execute(
        text(
            "INSERT INTO demo.segmento (idsegmento, nome, status, cpoe) "
            "VALUES (:id, 'ZZTEST Segmento Escores', 1, false)"
        ),
        {"id": _SEGMENT_SCORES},
    )
    session.execute(
        text(
            "INSERT INTO demo.segmentosetor (idsegmento, fkhospital, fksetor) "
            "VALUES (:id_segment, 1, :id_department)"
        ),
        {"id_segment": _SEGMENT_SCORES, "id_department": _DEPARTMENT_SCORES},
    )
    session_commit()

    for dose, frequency, count in (_HISTORY_LOW, _HISTORY_HIGH):
        session.execute(
            text(
                "INSERT INTO demo.prescricaoagg "
                "  (fkhospital, fksetor, idsegmento, fkmedicamento, fkunidademedida, "
                "   fkfrequencia, dose, doseconv, frequenciadia, peso, contagem) "
                "VALUES (1, :id_department, :id_segment, :id_drug, '1', "
                "        :frequency_id, :dose, :dose, :frequency, 999, :count)"
            ),
            {
                "id_department": _DEPARTMENT_SCORES,
                "id_segment": _SEGMENT_SCORES,
                "id_drug": _DRUG_HISTORY,
                # seed frequency whose daily frequency the trigger copies over
                "frequency_id": str(int(frequency)),
                "dose": dose,
                "frequency": frequency,
                "count": count,
            },
        )
    session_commit()

    yield

    _drop_drug(_DRUG_HISTORY)
    _drop_segment()


def _drug_attribute_segments(id_drug: int):
    """Segments the drug already has attributes configured for."""
    rows = session.execute(
        text(
            "SELECT idsegmento FROM demo.medatributos WHERE fkmedicamento = :id "
            "ORDER BY idsegmento"
        ),
        {"id": id_drug},
    ).fetchall()

    return [row[0] for row in rows]


@pytest.fixture
def pending_frequency():
    """A frequency whose daily frequency has not been converted yet."""
    session.execute(
        text(
            "INSERT INTO demo.frequencia (fkfrequencia, fkhospital, nome, frequenciadia) "
            "VALUES (:id, 1, 'ZZTEST Frequencia Pendente', NULL)"
        ),
        {"id": _PENDING_FREQUENCY},
    )
    session_commit()

    yield

    session.execute(
        text("DELETE FROM demo.frequencia WHERE fkfrequencia = :id"),
        {"id": _PENDING_FREQUENCY},
    )
    session_commit()


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
        # the scores are needed right away, unlike the segment-wide run
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

    def test_the_fold_format_is_discontinued(
        self, client, admin_headers, monkeypatch
    ):
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


class TestGenerateSegmentScores:
    """POST /outliers/generate/segment"""

    def test_outliers_are_rebuilt_from_the_aggregated_history(
        self, client, admin_headers, monkeypatch, segment_with_history
    ):
        """Each dose/frequency pair of the history becomes one outlier [200]"""
        lambda_client = _lambda_double(request_id="zztest-segment-request", status_code=202)
        monkeypatch.setattr(
            "services.outlier_service.aws.get_client", lambda *a, **k: lambda_client
        )

        response = client.post(
            _SEGMENT_URL, json={"idSegment": _SEGMENT_SCORES}, headers=admin_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.get_json()["data"] == {
            "request_id": "zztest-segment-request",
            "status_code": 202,
        }
        assert _outliers(_SEGMENT_SCORES) == [(50.0, 1.0, 5, None), (150.0, 2.0, 3, None)]

    def test_the_scoring_run_is_fired_and_not_waited_on(
        self, client, admin_headers, monkeypatch, segment_with_history
    ):
        """The caller polls the request id instead of holding the request [200]"""
        lambda_client = _lambda_double()
        monkeypatch.setattr(
            "services.outlier_service.aws.get_client", lambda *a, **k: lambda_client
        )

        client.post(
            _SEGMENT_URL, json={"idSegment": _SEGMENT_SCORES}, headers=admin_headers
        )

        assert _sent_payload(lambda_client) == {
            "command": "lambda_scores.process_segment_scores",
            "schema": _SCHEMA,
            "id_user": _CALLER_ID,
            "id_segment": _SEGMENT_SCORES,
        }
        assert lambda_client.calls[0]["InvocationType"] == "Event"

    def test_an_outlier_without_history_is_dropped(
        self, client, admin_headers, monkeypatch, segment_with_history
    ):
        """The rebuild starts from an empty segment, so stale rows do not survive [200]"""
        _create_outlier(_OUTLIER_STALE, _DRUG_STALE, _SEGMENT_SCORES, (999.0, 9.0, 1))

        lambda_client = _lambda_double()
        monkeypatch.setattr(
            "services.outlier_service.aws.get_client", lambda *a, **k: lambda_client
        )

        client.post(
            _SEGMENT_URL, json={"idSegment": _SEGMENT_SCORES}, headers=admin_headers
        )

        assert _outliers(_SEGMENT_SCORES, _DRUG_STALE) == []

    def test_the_new_outliers_get_their_drug_attributes(
        self, client, admin_headers, monkeypatch, segment_with_history
    ):
        """A drug scored in a segment it had no attributes in gets them copied [200]"""
        assert _drug_attribute_segments(_DRUG_HISTORY) == []

        lambda_client = _lambda_double()
        monkeypatch.setattr(
            "services.outlier_service.aws.get_client", lambda *a, **k: lambda_client
        )

        client.post(
            _SEGMENT_URL, json={"idSegment": _SEGMENT_SCORES}, headers=admin_headers
        )

        assert _SEGMENT_SCORES in _drug_attribute_segments(_DRUG_HISTORY)

    def test_a_segment_without_history_is_refused(
        self, client, admin_headers, monkeypatch
    ):
        """Without aggregated history there is nothing to build outliers from [400]"""
        lambda_client = _lambda_double()
        monkeypatch.setattr(
            "services.outlier_service.aws.get_client", lambda *a, **k: lambda_client
        )

        response = client.post(
            _SEGMENT_URL,
            json={"idSegment": _SEGMENT_WITHOUT_HISTORY},
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert lambda_client.calls == []
        assert _outliers(_SEGMENT_WITHOUT_HISTORY) == []

    def test_requires_write_segment_score(
        self, client, config_manager_headers, monkeypatch, segment_with_history
    ):
        """Scoring a whole segment is beyond the config manager role [401]"""
        lambda_client = _lambda_double()
        monkeypatch.setattr(
            "services.outlier_service.aws.get_client", lambda *a, **k: lambda_client
        )

        response = client.post(
            _SEGMENT_URL,
            json={"idSegment": _SEGMENT_SCORES},
            headers=config_manager_headers,
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert lambda_client.calls == []
        assert _outliers(_SEGMENT_SCORES) == []


class TestRefreshAgg:
    """GET /outliers/generate/refresh-agg"""

    def test_the_recalculation_is_handed_to_the_lambda(
        self, client, admin_headers, monkeypatch
    ):
        """The schema is all the recalculation needs, and it is fire and forget [200]"""
        lambda_client = _lambda_double(request_id="zztest-agg-request", status_code=202)
        monkeypatch.setattr(
            "services.outlier_service.aws.get_client", lambda *a, **k: lambda_client
        )

        response = client.get(_REFRESH_AGG_URL, headers=admin_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.get_json()["data"] == {
            "request_id": "zztest-agg-request",
            "status_code": 202,
        }
        assert _sent_payload(lambda_client) == {
            "command": "lambda_scores.recalculate_agg",
            "schema": _SCHEMA,
        }
        assert lambda_client.calls[0]["InvocationType"] == "Event"

    def test_a_pending_frequency_blocks_the_recalculation(
        self, client, admin_headers, monkeypatch, pending_frequency
    ):
        """An unconverted frequency would silently skew every dose bucket [400]"""
        lambda_client = _lambda_double()
        monkeypatch.setattr(
            "services.outlier_service.aws.get_client", lambda *a, **k: lambda_client
        )

        response = client.get(_REFRESH_AGG_URL, headers=admin_headers)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert lambda_client.calls == []

    def test_requires_write_segment_score(
        self, client, config_manager_headers, monkeypatch
    ):
        """Recalculating the whole history is beyond the config manager role [401]"""
        lambda_client = _lambda_double()
        monkeypatch.setattr(
            "services.outlier_service.aws.get_client", lambda *a, **k: lambda_client
        )

        response = client.get(_REFRESH_AGG_URL, headers=config_manager_headers)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert lambda_client.calls == []

