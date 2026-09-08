"""Tests: GET /reports/exams/raw

The raw-exams report is the one endpoint that hands a patient's laboratory
results over untransformed: no reference range, no segment configuration, no
alert. It exists so an integration can pull the results the backend received,
so what matters is exactly the part the service decides:

* the caller needs READ_REPORTS -- which every reading role holds, VIEWER
  included -- and ``idPatient`` is mandatory;
* the results are the patient's own, and only the ones from the last 30 days --
  the window is applied against the exam date, not against when the row was
  received;
* every identifier and the result value leave as strings (the report is
  consumed by clients that cannot be trusted with 64-bit numbers), and the
  date leaves as ISO-8601;
* the rows arrive grouped by exam type, newest result of each type first.

The seed dump's exams are all from 2019, so they sit outside the window by
construction: every test here inserts the results it expects to read back.
"""

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import bindparam, text

from tests.conftest import session, session_commit
from utils import status

URL = "/reports/exams/raw"

# patient / admission present in the seed data (see tests/integration/test_exams.py)
PATIENT_ID = 5
ADMISSION = 5

# another seeded patient, used to prove the report is scoped to one patient
OTHER_PATIENT_ID = 3

# a patient that has no exam at all
UNKNOWN_PATIENT_ID = 999999

# exam ids inserted by this module (kept clear of the 900001/900002 pair used
# by tests/integration/test_exams.py)
_ID_BASE = 951000

# the window the service asks the repository for
_WINDOW_DAYS = 30


def _url(id_patient=None):
    """The report URL, optionally naming the patient."""
    return URL if id_patient is None else f"{URL}?idPatient={id_patient}"


def _data(response):
    """The payload of a successful api_endpoint response."""
    return json.loads(response.data)["data"]


def _days_ago(days: int):
    """An exam date the given number of days in the past.

    Anchored at midday so the app's timezone (America/Sao_Paulo, applied per
    request) can never move a date across the day boundary the window is
    measured from.
    """
    return datetime.now().replace(
        hour=12, minute=0, second=0, microsecond=0
    ) - timedelta(days=days)


class _Exams:
    """Inserts exam results and removes exactly the rows it inserted."""

    def __init__(self):
        self.ids = []

    def add(
        self,
        type_exam: str,
        exam_date: datetime,
        value: float,
        unit: str = "mg/dL",
        id_patient: int = PATIENT_ID,
    ):
        """Insert one result and return its id."""
        id_exam = _ID_BASE + len(self.ids) + 1
        self.ids.append(id_exam)

        session.execute(
            text(
                "INSERT INTO demo.exame "
                "(fkexame, fkpessoa, nratendimento, dtexame, tpexame, resultado, "
                "unidade, created_by) "
                "VALUES (:id, :patient, :admission, :date, :type, :value, :unit, 1)"
            ),
            {
                "id": id_exam,
                "patient": id_patient,
                "admission": ADMISSION,
                "date": exam_date,
                "type": type_exam,
                "value": value,
                "unit": unit,
            },
        )
        session_commit()

        return id_exam

    def remove(self):
        """Drop every row this helper inserted."""
        if not self.ids:
            return

        session.execute(
            text("DELETE FROM demo.exame WHERE fkexame IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": self.ids},
        )
        session_commit()


@pytest.fixture
def exams():
    """A recorder for the exams a test inserts, cleaned up afterwards."""
    recorder = _Exams()
    yield recorder
    recorder.remove()


def test_raw_exams_requires_the_read_reports_permission(client, user_manager_headers):
    """GET /reports/exams/raw - a role without READ_REPORTS is refused [401 UNAUTHORIZED]"""
    response = client.get(_url(PATIENT_ID), headers=user_manager_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_raw_exams_is_open_to_a_read_only_role(client, viewer_headers, exams):
    """GET /reports/exams/raw - READ_REPORTS is enough: VIEWER may pull the results"""
    id_exam = exams.add("tgo", _days_ago(1), 1.0)

    response = client.get(_url(PATIENT_ID), headers=viewer_headers)

    assert response.status_code == status.HTTP_200_OK
    assert [i["idExam"] for i in _data(response)] == [str(id_exam)]


def test_raw_exams_without_a_patient_is_rejected(client, analyst_headers):
    """GET /reports/exams/raw - the patient is mandatory [400 BAD REQUEST]"""
    response = client.get(_url(), headers=analyst_headers)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert json.loads(response.data)["code"] == "errors.invalidParams"


def test_raw_exams_maps_every_column(client, analyst_headers, exams):
    """GET /reports/exams/raw - a result is reported with its full mapping"""
    exam_date = _days_ago(1)
    id_exam = exams.add("tgo", exam_date, 42.0)

    response = client.get(_url(PATIENT_ID), headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    assert _data(response) == [
        {
            "idExam": str(id_exam),
            "typeExam": "tgo",
            "idPatient": str(PATIENT_ID),
            "admissionNumber": str(ADMISSION),
            "dateExam": exam_date.isoformat(),
            "value": "42.0",
            "unit": "mg/dL",
        }
    ]


def test_raw_exams_reports_a_missing_unit_as_null(client, analyst_headers, exams):
    """GET /reports/exams/raw - a result stored without a unit keeps a null unit"""
    exams.add("tgp", _days_ago(1), 12.25, unit=None)

    response = client.get(_url(PATIENT_ID), headers=analyst_headers)

    assert _data(response)[0]["unit"] is None


def test_raw_exams_keeps_the_last_thirty_days(client, analyst_headers, exams):
    """GET /reports/exams/raw - a result from the edge of the window is still reported"""
    id_exam = exams.add("tgo", _days_ago(_WINDOW_DAYS), 1.0)

    response = client.get(_url(PATIENT_ID), headers=analyst_headers)

    assert [i["idExam"] for i in _data(response)] == [str(id_exam)]


def test_raw_exams_drops_what_is_older_than_the_window(client, analyst_headers, exams):
    """GET /reports/exams/raw - a result past the window is left out"""
    recent = exams.add("tgo", _days_ago(_WINDOW_DAYS - 1), 1.0)
    exams.add("tgo", _days_ago(_WINDOW_DAYS + 1), 2.0)

    response = client.get(_url(PATIENT_ID), headers=analyst_headers)

    assert [i["idExam"] for i in _data(response)] == [str(recent)]


def test_raw_exams_of_a_patient_with_only_old_results_is_empty(client, analyst_headers):
    """GET /reports/exams/raw - the seeded 2019 results are all outside the window"""
    response = client.get(_url(PATIENT_ID), headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    assert _data(response) == []


def test_raw_exams_of_an_unknown_patient_is_empty(client, analyst_headers):
    """GET /reports/exams/raw - a patient with no result at all reports an empty list"""
    response = client.get(_url(UNKNOWN_PATIENT_ID), headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    assert _data(response) == []


def test_raw_exams_are_scoped_to_the_requested_patient(client, analyst_headers, exams):
    """GET /reports/exams/raw - another patient's result is never reported"""
    mine = exams.add("tgo", _days_ago(1), 1.0)
    exams.add("tgo", _days_ago(1), 2.0, id_patient=OTHER_PATIENT_ID)

    response = client.get(_url(PATIENT_ID), headers=analyst_headers)

    assert [i["idExam"] for i in _data(response)] == [str(mine)]


def test_raw_exams_are_grouped_by_type_newest_first(client, analyst_headers, exams):
    """GET /reports/exams/raw - results come ordered by exam type, newest of each first"""
    old_tgo = exams.add("tgo", _days_ago(5), 1.0)
    new_tgo = exams.add("tgo", _days_ago(2), 2.0)
    old_creat = exams.add("creatinina", _days_ago(4), 0.5)
    new_creat = exams.add("creatinina", _days_ago(3), 2.5)

    response = client.get(_url(PATIENT_ID), headers=analyst_headers)

    assert [i["idExam"] for i in _data(response)] == [
        str(new_creat),
        str(old_creat),
        str(new_tgo),
        str(old_tgo),
    ]
