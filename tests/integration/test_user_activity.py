"""Tests: daily user activity counters (``public.usuario_atividade``)

Four actions are counted per user per day: signing in (``logins``), checking a
prescription (``checagens``), registering an intervention (``intervencoes``) and
writing a clinical note (``evolucoes``). ``user_activity_repository`` keeps one
row per (user, day) and bumps a single column with ``INSERT ... ON CONFLICT DO
UPDATE``, so the first action of the day creates the row and every later one
adds to what is already stored.

Nothing in the product reads these counters back — they feed usage reporting
outside the API — so a regression here is invisible until a report is wrong.
These tests pin both halves: the repository contract (one row per day, counters
that do not clobber each other) and the four call sites that reach it.

The repository rows are written straight to ``public``, which the whole suite
shares, so the end-to-end tests compare *deltas* rather than absolute counts:
every other test that authenticates bumps the demo user's login counter too.
"""

from datetime import date, datetime, timedelta

import pytest
from flask_jwt_extended import verify_jwt_in_request
from sqlalchemy import text

from mobile import app
from models.main import db
from models.prescription import PrescriptionClinicalNote
from repository import user_activity_repository
from security.role import Role
from tests.conftest import get_access, session, session_commit
from tests.utils.utils_test_prescription import create_basic_prescription

SCHEMA = "demo"
DEMO_USER_ID = 1

# ids reserved for this file: the suite cleanup drops usuario_atividade rows
# from 99900 up (see tests/conftest.py::_cleanup)
TEST_USER_ID = 99900
OTHER_TEST_USER_ID = 99901

COUNTERS = {
    "logins": user_activity_repository.increment_logins,
    "checagens": user_activity_repository.increment_checks,
    "intervencoes": user_activity_repository.increment_interventions,
    "evolucoes": user_activity_repository.increment_evolutions,
}


def _rows(user_id: int):
    """Every usuario_atividade row of a user, oldest day first"""
    result = session.execute(
        text(
            "SELECT dt_atividade, logins, checagens, intervencoes, evolucoes, "
            "created_at, updated_at "
            "FROM public.usuario_atividade WHERE idusuario = :id "
            "ORDER BY dt_atividade"
        ),
        {"id": user_id},
    )

    return [dict(row._mapping) for row in result]


def _today_row(user_id: int):
    """Today's usuario_atividade row of a user, or None when absent"""
    for row in _rows(user_id):
        if row["dt_atividade"].date() == date.today():
            return row

    return None


def _counter(user_id: int, column: str) -> int:
    """Today's value of one counter, 0 when the row or the column is empty"""
    row = _today_row(user_id)

    if row is None or row[column] is None:
        return 0

    return row[column]


def _delete_rows(*user_ids):
    session.execute(
        text("DELETE FROM public.usuario_atividade WHERE idusuario = ANY(:ids)"),
        {"ids": list(user_ids)},
    )
    session_commit()


@pytest.fixture
def clean_activity():
    """Drop the synthetic users' rows before and after each test"""
    _delete_rows(TEST_USER_ID, OTHER_TEST_USER_ID)
    yield
    _delete_rows(TEST_USER_ID, OTHER_TEST_USER_ID)


@pytest.fixture
def repository_context(client):
    """Run repository calls inside a request context and commit them.

    The repository only issues the statement — the service layer owns the
    commit — so the test has to close the transaction itself before reading the
    row back through the suite's own session.
    """
    token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    with app.test_request_context(headers={"Authorization": f"Bearer {token}"}):
        verify_jwt_in_request()
        db.session.connection(
            execution_options={"schema_translate_map": {None: SCHEMA}}
        )
        try:
            yield db.session
        finally:
            db.session.rollback()
            db.session.remove()


# ---------------------------------------------------------------------------
# repository contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("column", sorted(COUNTERS))
def test_the_first_action_of_the_day_creates_the_row(
    column, clean_activity, repository_context
):
    """Each counter has its own increment, and the first one opens today's row"""
    COUNTERS[column](TEST_USER_ID)
    repository_context.commit()

    row = _today_row(TEST_USER_ID)

    assert row is not None
    assert row[column] == 1
    assert row["created_at"] is not None


def test_a_new_row_carries_no_update_timestamp(clean_activity, repository_context):
    """A row that was just created has not been updated yet"""
    user_activity_repository.increment_logins(TEST_USER_ID)
    repository_context.commit()

    assert _today_row(TEST_USER_ID)["updated_at"] is None


def test_further_actions_add_to_the_same_daily_row(clean_activity, repository_context):
    """Three logins on the same day are one row holding 3, not three rows"""
    for _ in range(3):
        user_activity_repository.increment_logins(TEST_USER_ID)
    repository_context.commit()

    rows = _rows(TEST_USER_ID)

    assert len(rows) == 1
    assert rows[0]["logins"] == 3
    assert rows[0]["updated_at"] is not None


def test_counters_do_not_clobber_each_other(clean_activity, repository_context):
    """Bumping one counter leaves the others of the same row untouched"""
    user_activity_repository.increment_logins(TEST_USER_ID)
    user_activity_repository.increment_logins(TEST_USER_ID)
    user_activity_repository.increment_checks(TEST_USER_ID)
    user_activity_repository.increment_interventions(TEST_USER_ID)
    repository_context.commit()

    row = _today_row(TEST_USER_ID)

    assert row["logins"] == 2
    assert row["checagens"] == 1
    assert row["intervencoes"] == 1
    # never touched: an untouched counter stays null rather than becoming 0
    assert row["evolucoes"] is None


def test_counters_are_kept_per_user(clean_activity, repository_context):
    """Two users acting on the same day get one row each"""
    user_activity_repository.increment_logins(TEST_USER_ID)
    user_activity_repository.increment_logins(OTHER_TEST_USER_ID)
    user_activity_repository.increment_logins(OTHER_TEST_USER_ID)
    repository_context.commit()

    assert _counter(TEST_USER_ID, "logins") == 1
    assert _counter(OTHER_TEST_USER_ID, "logins") == 2


def test_a_new_day_opens_a_new_row(clean_activity, repository_context):
    """Yesterday's counters are history: today starts from scratch"""
    session.execute(
        text(
            "INSERT INTO public.usuario_atividade "
            "(idusuario, dt_atividade, logins, created_at) "
            "VALUES (:id, :day, 7, :created_at)"
        ),
        {
            "id": TEST_USER_ID,
            "day": datetime.combine(
                date.today() - timedelta(days=1), datetime.min.time()
            ),
            "created_at": datetime.now() - timedelta(days=1),
        },
    )
    session_commit()

    user_activity_repository.increment_logins(TEST_USER_ID)
    repository_context.commit()

    rows = _rows(TEST_USER_ID)

    assert len(rows) == 2
    assert rows[0]["logins"] == 7  # yesterday, untouched
    assert rows[1]["logins"] == 1  # today


# ---------------------------------------------------------------------------
# the four call sites
# ---------------------------------------------------------------------------


def test_authenticating_counts_a_login(client):
    """POST /authenticate bumps the login counter of the user who signed in"""
    before = _counter(DEMO_USER_ID, "logins")

    response = client.post(
        "/authenticate",
        json={"email": "demo", "password": "demo"},
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )

    assert response.status_code == 200
    assert _counter(DEMO_USER_ID, "logins") == before + 1


def test_a_refused_sign_in_counts_nothing(client):
    """A wrong password is rejected before the counter is reached"""
    before = _counter(DEMO_USER_ID, "logins")

    response = client.post(
        "/authenticate",
        json={"email": "demo", "password": "wrong-password"},
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )

    assert response.status_code == 400
    assert _counter(DEMO_USER_ID, "logins") == before


def test_checking_a_prescription_counts_a_check(client, analyst_headers):
    """POST /prescriptions/status with status "s" bumps the check counter"""
    prescription = create_basic_prescription()
    before = _counter(DEMO_USER_ID, "checagens")

    response = client.post(
        "/prescriptions/status",
        json={
            "idPrescription": prescription.id,
            "status": "s",
            "evaluationTime": 0,
            "alerts": [],
            "fastCheck": False,
        },
        headers=analyst_headers,
    )

    assert response.status_code == 200
    assert _counter(DEMO_USER_ID, "checagens") == before + 1


def test_undoing_a_check_counts_nothing(client, analyst_headers):
    """Only a check counts: reverting one back to pending does not"""
    prescription = create_basic_prescription()
    client.post(
        "/prescriptions/status",
        json={
            "idPrescription": prescription.id,
            "status": "s",
            "evaluationTime": 0,
            "alerts": [],
            "fastCheck": False,
        },
        headers=analyst_headers,
    )

    before = _counter(DEMO_USER_ID, "checagens")

    response = client.post(
        "/prescriptions/status",
        json={
            "idPrescription": prescription.id,
            "status": "0",
            "evaluationTime": 0,
            "alerts": [],
            "fastCheck": False,
        },
        headers=analyst_headers,
    )

    assert response.status_code == 200
    assert _counter(DEMO_USER_ID, "checagens") == before


def test_registering_an_intervention_counts_it(client, analyst_headers):
    """PUT /intervention bumps the intervention counter when one is created"""
    prescription = create_basic_prescription()
    id_prescription_drug = int(f"{prescription.id}001")

    before = _counter(DEMO_USER_ID, "intervencoes")

    response = client.put(
        "/intervention",
        json={
            "status": "s",
            "admissionNumber": prescription.admissionNumber,
            "idInterventionReason": [5],
            "error": False,
            "cost": False,
            "observation": "teste",
            "idPrescriptionDrug": str(id_prescription_drug),
        },
        headers=analyst_headers,
    )

    assert response.status_code == 200
    assert _counter(DEMO_USER_ID, "intervencoes") == before + 1


def test_editing_an_intervention_counts_nothing(client, analyst_headers):
    """Only a new intervention counts: editing an existing one does not"""
    prescription = create_basic_prescription()
    payload = {
        "status": "s",
        "admissionNumber": prescription.admissionNumber,
        "idInterventionReason": [5],
        "error": False,
        "cost": False,
        "observation": "teste",
        "idPrescriptionDrug": str(int(f"{prescription.id}001")),
    }

    created = client.put("/intervention", json=payload, headers=analyst_headers)
    assert created.status_code == 200

    before = _counter(DEMO_USER_ID, "intervencoes")

    response = client.put(
        "/intervention",
        json={
            **payload,
            "idIntervention": created.get_json()["data"][0]["idIntervention"],
            "observation": "teste editado",
        },
        headers=analyst_headers,
    )

    assert response.status_code == 200
    assert _counter(DEMO_USER_ID, "intervencoes") == before


def test_writing_a_clinical_note_counts_an_evolution(client, analyst_headers):
    """POST /prescription-clinical-note bumps the evolution counter"""
    prescription = create_basic_prescription()
    before = _counter(DEMO_USER_ID, "evolucoes")

    response = client.post(
        "/prescription-clinical-note",
        json={
            "idPrescription": prescription.id,
            "text": "evolução de teste",
            "tpStatus": 0,
        },
        headers=analyst_headers,
    )

    assert response.status_code == 200
    assert _counter(DEMO_USER_ID, "evolucoes") == before + 1

    session.query(PrescriptionClinicalNote).filter(
        PrescriptionClinicalNote.idPrescription == prescription.id
    ).delete()
    session_commit()


def test_editing_a_clinical_note_counts_nothing(client, analyst_headers):
    """Only a new note counts: rewriting the same one does not"""
    prescription = create_basic_prescription()
    created = client.post(
        "/prescription-clinical-note",
        json={
            "idPrescription": prescription.id,
            "text": "evolução de teste",
            "tpStatus": 0,
        },
        headers=analyst_headers,
    )

    assert created.status_code == 200
    before = _counter(DEMO_USER_ID, "evolucoes")

    response = client.post(
        "/prescription-clinical-note",
        json={
            "id": created.get_json()["data"]["id"],
            "idPrescription": prescription.id,
            "text": "evolução corrigida",
            "tpStatus": 0,
        },
        headers=analyst_headers,
    )

    assert response.status_code == 200
    assert _counter(DEMO_USER_ID, "evolucoes") == before

    session.query(PrescriptionClinicalNote).filter(
        PrescriptionClinicalNote.idPrescription == prescription.id
    ).delete()
    session_commit()
