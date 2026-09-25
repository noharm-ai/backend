"""Tests: GET /exams/<admission> merging DynamoDB results with PostgreSQL ones

Exam results reach the backend twice. The integration writes them to DynamoDB
as soon as they are released (see
``exams_repository.get_exams_by_patient_from_dynamodb``), and they land in the
``exame`` table in PostgreSQL later. ``exams_service.get_exams_by_admission``
reads both and merges them, keyed by ``(fkexame, tpexame)``:

* a result only DynamoDB knows about is reported right away, tagged
  ``source: "dynamodb"``;
* once the same result reaches PostgreSQL, the relational row wins — it is the
  one that carries the manual-entry author and survives a DynamoDB outage;
* a DynamoDB item with no id, no type or no readable date is dropped, since it
  cannot be keyed or ordered.

``exams_repository.get_exams_by_patient_from_dynamodb`` short-circuits to an
empty list under ENV=test, so these tests patch it to feed the merge the items
the integration would have written.
"""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import bindparam, text

from tests.conftest import session, session_commit
from utils import status

# Admission / patient present in the seed data (see tests/integration/test_patient.py)
ADMISSION = 5
PATIENT_ID = 5
SEGMENT = 1

# An exam type of our own, so the seed results never collide with these rows
EXAM_TYPE = "zzdyn"
EXAM_IDS = [910001, 910002]

RECENT = datetime.today() - timedelta(days=1)
OLDER = datetime.today() - timedelta(days=5)


def _url():
    return f"/exams/{ADMISSION}?idSegment={SEGMENT}"


def _dynamo_item(id_exam: int, exam_date, value="1.5", type_exam=EXAM_TYPE):
    """One raw item shaped the way the integration writes it to DynamoDB."""
    return {
        "fkexame": id_exam,
        "fkpessoa": PATIENT_ID,
        "nratendimento": ADMISSION,
        "tpexame": type_exam,
        "resultado": value,
        "unidade": "mg/dL",
        "dtexame": exam_date.isoformat() if hasattr(exam_date, "isoformat") else exam_date,
    }


def _add_postgres_exam(id_exam: int, exam_date: datetime, value: float, type_exam=EXAM_TYPE):
    """Insert the relational counterpart of a result."""
    session.execute(
        text(
            "INSERT INTO demo.exame "
            "(fkexame, fkpessoa, nratendimento, dtexame, tpexame, resultado, unidade) "
            "VALUES (:id, :patient, :admission, :date, :tp, :value, 'mg/dL')"
        ),
        {
            "id": id_exam,
            "patient": PATIENT_ID,
            "admission": ADMISSION,
            "date": exam_date,
            "tp": type_exam,
            "value": value,
        },
    )
    session_commit()


@pytest.fixture(autouse=True)
def clean_dynamo_exam_setup():
    """Remove the exam type and the relational results these tests create."""

    def _clean():
        session.execute(
            text("DELETE FROM demo.exame WHERE fkexame IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": EXAM_IDS},
        )
        session.execute(
            text(
                "DELETE FROM demo.segmentoexame "
                "WHERE idsegmento = :seg AND tpexame = :tp"
            ),
            {"seg": SEGMENT, "tp": EXAM_TYPE},
        )
        session_commit()

    _clean()
    # configure the type so the result is reported with its reference range
    session.execute(
        text(
            "INSERT INTO demo.segmentoexame "
            "(idsegmento, tpexame, abrev, nome, min, max, referencia, posicao, ativo, update_by) "
            "VALUES (:seg, :tp, 'ZZDYN', 'Exame DynamoDB', 0, 10, '', 90, true, 1)"
        ),
        {"seg": SEGMENT, "tp": EXAM_TYPE},
    )
    session_commit()

    yield

    _clean()


def _get_exams(client, headers, dynamo_items):
    """Call the endpoint with DynamoDB returning the given items."""
    with patch(
        "services.exams_service.exams_repository.get_exams_by_patient_from_dynamodb",
        return_value=dynamo_items,
    ):
        return client.get(_url(), headers=headers)


def test_dynamodb_only_result_is_reported(client, analyst_headers):
    """A result PostgreSQL has not received yet still reaches the exam list."""
    response = _get_exams(
        client, analyst_headers, [_dynamo_item(EXAM_IDS[0], RECENT, value="2.5")]
    )

    assert response.status_code == status.HTTP_200_OK
    exam = response.get_json()["data"][EXAM_TYPE]

    assert exam["value"] == 2.5
    assert exam["source"] == "dynamodb"
    assert exam["date"] == RECENT.isoformat()


def test_postgres_result_is_tagged_as_such(client, analyst_headers):
    """With DynamoDB silent, the relational row is reported and tagged postgres."""
    _add_postgres_exam(EXAM_IDS[0], RECENT, 2.5)

    response = _get_exams(client, analyst_headers, [])

    assert response.status_code == status.HTTP_200_OK
    exam = response.get_json()["data"][EXAM_TYPE]

    assert exam["value"] == 2.5
    assert exam["source"] == "postgres"


def test_postgres_wins_when_both_sources_carry_the_same_result(client, analyst_headers):
    """The same (fkexame, tpexame) is not reported twice: the relational row prevails."""
    _add_postgres_exam(EXAM_IDS[0], RECENT, 2.5)

    response = _get_exams(
        client,
        analyst_headers,
        # a stale copy of the very same result
        [_dynamo_item(EXAM_IDS[0], OLDER, value="9.9")],
    )

    assert response.status_code == status.HTTP_200_OK
    exam = response.get_json()["data"][EXAM_TYPE]

    assert exam["value"] == 2.5
    assert exam["source"] == "postgres"
    assert len(exam["history"]) == 1


def test_both_sources_are_merged_newest_first(client, analyst_headers):
    """Distinct results of one type are merged into a single history, newest first."""
    _add_postgres_exam(EXAM_IDS[0], OLDER, 1.0)

    response = _get_exams(
        client, analyst_headers, [_dynamo_item(EXAM_IDS[1], RECENT, value="4.0")]
    )

    assert response.status_code == status.HTTP_200_OK
    exam = response.get_json()["data"][EXAM_TYPE]

    # the most recent result of the type is the one reported at the top level
    assert exam["value"] == 4.0
    assert exam["source"] == "dynamodb"

    history = exam["history"]
    assert [h["value"] for h in history] == [4.0, 1.0]
    assert [h["source"] for h in history] == ["dynamodb", "postgres"]
    assert [h["idExam"] for h in history] == [EXAM_IDS[1], EXAM_IDS[0]]


def test_dynamodb_result_is_not_flagged_as_manual(client, analyst_headers):
    """Integration results carry no author, so they never read as manually entered."""
    response = _get_exams(
        client, analyst_headers, [_dynamo_item(EXAM_IDS[0], RECENT)]
    )

    assert response.status_code == status.HTTP_200_OK
    history = response.get_json()["data"][EXAM_TYPE]["history"]

    assert history[0]["manual"] is False
    assert history[0]["admissionNumber"] == ADMISSION


@pytest.mark.parametrize("missing", ["fkexame", "tpexame", "dtexame"])
def test_item_without_a_key_field_is_dropped(client, analyst_headers, missing):
    """An item that cannot be keyed or ordered is skipped instead of breaking the list."""
    item = _dynamo_item(EXAM_IDS[0], RECENT)
    del item[missing]

    response = _get_exams(client, analyst_headers, [item])

    assert response.status_code == status.HTTP_200_OK
    assert EXAM_TYPE not in response.get_json()["data"]


def test_item_with_an_unreadable_date_is_dropped(client, analyst_headers):
    """A date the parser cannot read drops the item rather than the whole request."""
    response = _get_exams(
        client, analyst_headers, [_dynamo_item(EXAM_IDS[0], "not a date")]
    )

    assert response.status_code == status.HTTP_200_OK
    assert EXAM_TYPE not in response.get_json()["data"]


def test_a_dropped_item_does_not_hide_a_valid_one(client, analyst_headers):
    """Skipping a malformed item leaves the rest of the batch intact."""
    broken = _dynamo_item(EXAM_IDS[0], RECENT)
    del broken["tpexame"]

    response = _get_exams(
        client,
        analyst_headers,
        [broken, _dynamo_item(EXAM_IDS[1], RECENT, value="3.0")],
    )

    assert response.status_code == status.HTTP_200_OK
    exam = response.get_json()["data"][EXAM_TYPE]

    assert exam["value"] == 3.0
    assert exam["source"] == "dynamodb"
