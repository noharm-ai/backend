"""Tests: POST /prescriptions/start-evaluation and POST /prescriptions/status-list

Two pharmacists may open the same prescription at once, so the frontend polls
these endpoints to show who else is on the screen and whether a prescription has
been checked in the meantime.

The presence store itself is DynamoDB, and it short-circuits under ENV=test (see
``repository.prescription_presence_repository``), so it is replaced here with a
recorder. What is left is exactly the backend's own share of the feature, and
that is what these tests pin down:

* an unknown or missing prescription id is refused before the store is touched;
* the heartbeat -- "I am editing this" -- is only recorded for a caller who can
  actually write the prescription, so a read-only viewer never appears as one of
  the editors;
* the partition key carries the caller's schema, so presence never leaks across
  tenants;
* whatever the store returns is normalised before it reaches the client.

``status-list`` is the cheap companion poll, and it has its own contract: it
never joins, it drops ids that are not numbers, and it stays silent about
prescriptions that do not exist.
"""

import json

import pytest
from sqlalchemy import text

from repository import prescription_presence_repository
from tests.conftest import session, session_commit
from tests.utils import utils_test_prescription
from utils import status

START_URL = "/prescriptions/start-evaluation"
STATUS_URL = "/prescriptions/status-list"

# the user behind every fixture in tests.conftest.get_access
CALLER_ID = 1
CALLER_NAME = "Demonstração"
CALLER_SCHEMA = "demo"

# far outside the seed range and outside the >= 100000 range the test helpers use
MISSING_PRESCRIPTION = 999999999

# demo.prescricao.status, as set by /prescriptions/status
CHECKED = "s"
OPEN = "0"


def _create_prescription(prescription_status: str) -> int:
    """Write a prescription in a known status and return its id.

    Written rather than taken from the seed dump: the poll asserts on the status,
    and the seed statuses are mutated by other modules. The id comes from the
    shared >= 100000 counter, so tests.conftest cleans it up.

    The status is set with an UPDATE because the BEFORE INSERT trigger on
    demo.prescricao rewrites the row through public.upsert_prescricao, which
    normalises a new prescription back to "not checked".
    """
    id_prescription = utils_test_prescription.test_counters["id_prescription"]
    utils_test_prescription.test_counters["id_prescription"] += 1

    utils_test_prescription.create_prescription(
        id=id_prescription,
        admissionNumber=1,
        idPatient=1,
    )

    session.execute(
        text("UPDATE demo.prescricao SET status = :status WHERE fkprescricao = :id"),
        {"status": prescription_status, "id": id_prescription},
    )
    session_commit()

    return id_prescription


@pytest.fixture
def open_prescription() -> int:
    """A prescription still waiting to be checked."""
    return _create_prescription(OPEN)


@pytest.fixture
def checked_prescription() -> int:
    """A prescription a pharmacist has already checked."""
    return _create_prescription(CHECKED)


@pytest.fixture(autouse=True)
def presence(monkeypatch):
    """Replace the DynamoDB presence store with a recorder.

    ``heartbeats`` collects every call, and ``viewers`` is what the store hands
    back for the prescription being opened.
    """
    recorder = {"heartbeats": [], "viewers": []}

    def _record_heartbeat(schema, id_prescription, user_id, user_name):
        recorder["heartbeats"].append(
            {
                "schema": schema,
                "id_prescription": id_prescription,
                "user_id": user_id,
                "user_name": user_name,
            }
        )
        return {}

    def _get_active_viewers(schema, id_prescription):
        recorder["queried"] = {"schema": schema, "id_prescription": id_prescription}
        return recorder["viewers"]

    monkeypatch.setattr(
        prescription_presence_repository, "record_heartbeat", _record_heartbeat
    )
    monkeypatch.setattr(
        prescription_presence_repository, "get_active_viewers", _get_active_viewers
    )

    return recorder


def _start(client, headers, id_prescription):
    """Open a prescription for evaluation."""
    return client.post(
        START_URL,
        data=json.dumps({"idPrescription": id_prescription}),
        headers=headers,
    )


def _status(client, headers, id_prescription_list):
    """Poll the status of a list of prescriptions."""
    return client.post(
        STATUS_URL,
        data=json.dumps({"idPrescriptionList": id_prescription_list}),
        headers=headers,
    )


def _data(response):
    """The payload of a successful api_endpoint response."""
    return json.loads(response.data)["data"]


# --- the prescription has to exist --------------------------------------------


def test_an_unknown_prescription_is_refused(client, analyst_headers, presence):
    """No heartbeat is recorded for a prescription that does not exist [400]."""
    response = _start(client, analyst_headers, MISSING_PRESCRIPTION)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidRegister"
    assert presence["heartbeats"] == []


def test_a_missing_prescription_id_is_refused(client, analyst_headers, presence):
    """An absent idPrescription is the same case, not a lookup for NULL [400]."""
    response = client.post(START_URL, data=json.dumps({}), headers=analyst_headers)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidRegister"
    assert presence["heartbeats"] == []


# --- who counts as an editor --------------------------------------------------


def test_a_user_who_can_write_is_recorded_as_editing(
    client, analyst_headers, presence, open_prescription
):
    """PRESCRIPTION_ANALYST holds WRITE_PRESCRIPTION, so the heartbeat lands.

    The recorded name is read from the database rather than the token, since it
    is what the other viewers will see on their screen.
    """
    response = _start(client, analyst_headers, open_prescription)

    assert response.status_code == status.HTTP_200_OK
    assert presence["heartbeats"] == [
        {
            "schema": CALLER_SCHEMA,
            "id_prescription": open_prescription,
            "user_id": CALLER_ID,
            "user_name": CALLER_NAME,
        }
    ]


def test_a_read_only_user_is_not_recorded_as_editing(
    client, viewer_headers, presence, open_prescription
):
    """VIEWER can read the prescription but not write it, so it stays invisible
    to the other viewers -- and still gets the list of who is editing [200 OK]."""
    presence["viewers"] = [
        {"userId": "7", "userName": "Outro", "startDate": "2026-01-01T12:00:00"}
    ]

    response = _start(client, viewer_headers, open_prescription)

    assert response.status_code == status.HTTP_200_OK
    assert presence["heartbeats"] == []
    assert _data(response) == [
        {"userId": 7, "userName": "Outro", "startDate": "2026-01-01T12:00:00"}
    ]


def test_presence_is_queried_within_the_callers_schema(
    client, analyst_headers, presence, open_prescription
):
    """The lookup is scoped by the JWT schema, never by the request [200 OK]."""
    _start(client, analyst_headers, open_prescription)

    assert presence["queried"] == {
        "schema": CALLER_SCHEMA,
        "id_prescription": open_prescription,
    }


# --- what the client is told ---------------------------------------------------


def test_nobody_else_on_the_screen_is_an_empty_list(
    client, analyst_headers, presence, open_prescription
):
    """The common case: the caller is alone [200 OK]."""
    presence["viewers"] = []

    assert _data(_start(client, analyst_headers, open_prescription)) == []


def test_viewers_are_normalised_before_they_reach_the_client(
    client, analyst_headers, presence, open_prescription
):
    """DynamoDB hands back numbers as Decimal and may omit attributes, so ids
    are coerced to int and the optional fields default to None [200 OK]."""
    presence["viewers"] = [
        {"userId": "12", "userName": "Com nome", "startDate": "2026-01-01T12:00:00"},
        {"userId": 13},
    ]

    assert _data(_start(client, analyst_headers, open_prescription)) == [
        {"userId": 12, "userName": "Com nome", "startDate": "2026-01-01T12:00:00"},
        {"userId": 13, "userName": None, "startDate": None},
    ]


def test_a_role_without_read_prescription_cannot_open_one(
    client, user_manager_headers, presence, open_prescription
):
    """USER_MANAGER holds no READ_PRESCRIPTION [401]."""
    response = _start(client, user_manager_headers, open_prescription)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert presence["heartbeats"] == []


# --- the status poll ----------------------------------------------------------


def test_status_list_returns_the_status_of_each_prescription(
    client, analyst_headers, open_prescription, checked_prescription
):
    """The poll answers with the stored status, ids as strings for the frontend."""
    response = _status(
        client, analyst_headers, [open_prescription, checked_prescription]
    )

    assert response.status_code == status.HTTP_200_OK

    by_id = {r["idPrescription"]: r["status"] for r in _data(response)}
    assert by_id == {
        str(open_prescription): OPEN,
        str(checked_prescription): CHECKED,
    }


def test_status_list_stays_silent_about_prescriptions_that_do_not_exist(
    client, analyst_headers, open_prescription
):
    """Unknown ids are dropped rather than reported as an error [200 OK]."""
    response = _status(
        client, analyst_headers, [open_prescription, MISSING_PRESCRIPTION]
    )

    assert [r["idPrescription"] for r in _data(response)] == [str(open_prescription)]


@pytest.mark.parametrize(
    "id_list",
    [[], [None], [0], ["not-a-number"]],
    ids=["empty", "null", "zero", "text"],
)
def test_status_list_never_queries_on_unusable_input(client, analyst_headers, id_list):
    """The poll runs on every screen refresh, so bad input is answered with an
    empty list instead of a 500."""
    response = _status(client, analyst_headers, id_list)

    assert response.status_code == status.HTTP_200_OK
    assert _data(response) == []


def test_one_bad_id_discards_the_whole_batch(
    client, analyst_headers, open_prescription
):
    """The route parses the batch as a unit, so a single unparseable id costs the
    good ones too. Pinned because the frontend must re-poll, not show stale rows."""
    response = _status(client, analyst_headers, [open_prescription, "not-a-number"])

    assert response.status_code == status.HTTP_200_OK
    assert _data(response) == []


def test_status_list_accepts_ids_sent_as_strings(
    client, analyst_headers, open_prescription
):
    """The frontend sends ids as strings, since they overflow a JS number."""
    response = _status(client, analyst_headers, [str(open_prescription)])

    assert _data(response) == [
        {"idPrescription": str(open_prescription), "status": OPEN}
    ]


def test_a_role_without_read_prescription_cannot_poll_status(
    client, user_manager_headers, open_prescription
):
    """The poll is gated by the same permission as the prescription itself [401]."""
    response = _status(client, user_manager_headers, [open_prescription])

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
