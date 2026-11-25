"""Integration tests for the last department of ``GET /prescriptions/<id>``.

The view shows the department of the admission's previous prescription: the one
with the highest id below the viewed one, dated within a month of it. The ids of
a schema mix forms of very different magnitudes (an aggregated prescription has
a much longer id than the prescriptions it aggregates) and are not ordered by
date, so the lookup must keep ordering by the id, never by the date.

The query orders by an expression of the id so that the planner can't walk the
primary key backwards (on a large table it visits every longer id of other
admissions first); these tests pin the row it returns, not its plan.
"""

import re
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from models.prescription import Prescription
from tests.conftest import session, session_commit
from tests.utils import utils_test_prescription

_ADMISSION = 960100
_OTHER_ADMISSION = 960199

# the viewed prescription: a long (16-digit) id, like an aggregated one
_VIEWED = 1960100000000001

# (id, admission, department, days before the viewed prescription)
_EARLIER_IN_WINDOW_LOWER_ID = (960101, _ADMISSION, 2, 1)
# the expected row: the highest id below the viewed one within the window,
# though dated before the one with a lower id (ordering by date would miss it)
_EXPECTED = (960102, _ADMISSION, 4, 10)
# a higher id below the viewed one, but out of the one-month window
_OUT_OF_WINDOW = (96010000000003, _ADMISSION, 5, 60)
# a higher id than the viewed one, in the window
_HIGHER_THAN_VIEWED = (1960100000000002, _ADMISSION, 6, 1)
# an id between the expected and the viewed ones, of another admission
_OTHER_ADMISSION_ROW = (96010000000009, _OTHER_ADMISSION, 7, 1)

_ROWS = [
    _EARLIER_IN_WINDOW_LOWER_ID,
    _EXPECTED,
    _OUT_OF_WINDOW,
    _HIGHER_THAN_VIEWED,
    _OTHER_ADMISSION_ROW,
]
_IDS = [_VIEWED] + [row[0] for row in _ROWS]


def _delete_rows():
    """Removes the prescriptions these tests create"""
    session.query(Prescription).filter(Prescription.id.in_(_IDS)).delete(
        synchronize_session=False
    )
    session_commit()


@pytest.fixture
def admission_with_previous_prescriptions():
    """The viewed prescription and the admission's (and another's) others"""
    _delete_rows()

    now = datetime.now()
    utils_test_prescription.create_prescription(
        id=_VIEWED,
        admissionNumber=_ADMISSION,
        idPatient=1,
        idDepartment=1,
        date=now,
    )
    for id_prescription, admission, id_department, days_before in _ROWS:
        utils_test_prescription.create_prescription(
            id=id_prescription,
            admissionNumber=admission,
            idPatient=1,
            idDepartment=id_department,
            date=now - timedelta(days=days_before),
        )

    yield _VIEWED

    _delete_rows()


@pytest.fixture
def statements():
    """The SQL statements executed from the moment the list is cleared"""
    executed = []

    def record(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        """Keeps the statement with its whitespace collapsed"""
        executed.append(" ".join(statement.split()))

    event.listen(Engine, "before_cursor_execute", record)
    try:
        yield executed
    finally:
        event.remove(Engine, "before_cursor_execute", record)


def test_last_department_is_the_highest_id_below_the_viewed_one_in_the_window(
    client, analyst_headers, admission_with_previous_prescriptions
):
    """Neither the date order, the longer ids of other admissions, a higher id
    nor a prescription out of the window decide the last department"""
    response = client.get(
        f"/prescriptions/{admission_with_previous_prescriptions}",
        headers=analyst_headers,
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["lastDepartment"] == "Setor Pediatrico 1"


def test_last_department_does_not_order_by_the_bare_primary_key(
    client, analyst_headers, admission_with_previous_prescriptions, statements
):
    """The lookup orders by an expression of the id: ordering by the bare
    primary key lets the planner walk the whole table backwards"""
    statements.clear()
    response = client.get(
        f"/prescriptions/{admission_with_previous_prescriptions}",
        headers=analyst_headers,
    )
    assert response.status_code == 200

    lookups = [
        s
        for s in statements
        if re.search(r"FROM demo\.prescricao LEFT OUTER JOIN demo\.setor\b", s)
    ]
    assert len(lookups) == 1
    assert re.search(r"ORDER BY demo\.prescricao\.fkprescricao \+ ", lookups[0])
