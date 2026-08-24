"""Integration tests for GET /prescriptions/search (prescription_service.search).

The fast search accepts a single term and matches it against:
  * a prescription id;
  * an admission number, restricted to aggregated prescriptions already in
    effect (agg = true and date <= today);
  * an admission number of a conciliation prescription (concilia is not null).

Regulation solicitations are also searched, but only when the caller holds
READ_REGULATION *and* the REGULATION feature is enabled for the schema — the
test schema has no regulation configuration, so that branch is covered only by
the permission assertions below.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from tests.conftest import get_access, make_headers, session, session_commit
from tests.utils.utils_test_prescription import create_prescription

from models.prescription import Patient
from security.role import Role

# ids/admission numbers well above the ranges used by the shared counters in
# tests/utils/utils_test_prescription.py, still inside the cleanup range (>= 100000)
ADMISSION = 990001
OTHER_ADMISSION = 990002

PRESC_AGG_TODAY = 990010
PRESC_REGULAR = 990011
PRESC_AGG_FUTURE = 990012
PRESC_CONCILIA = 990013
PRESC_OTHER_ADMISSION = 990020

BIRTHDATE = datetime(1980, 5, 4)
ADMISSION_DATE = datetime(2020, 12, 1)


@pytest.fixture
def seed_search_data():
    """Create a patient with prescriptions covering every search branch."""
    patient = Patient()
    patient.admissionNumber = ADMISSION
    patient.idPatient = 1
    patient.idHospital = 1
    patient.admissionDate = ADMISSION_DATE
    patient.birthdate = BIRTHDATE
    patient.gender = "F"
    session.add(patient)
    session_commit()

    now = datetime.now()

    # aggregated and already in effect: reachable by id and by admission number
    create_prescription(
        id=PRESC_AGG_TODAY,
        admissionNumber=ADMISSION,
        idPatient=1,
        date=now - timedelta(hours=1),
        agg=True,
        status="0",
    )
    # not aggregated: reachable by id only
    create_prescription(
        id=PRESC_REGULAR,
        admissionNumber=ADMISSION,
        idPatient=1,
        date=now - timedelta(hours=2),
        status="s",
    )
    # aggregated but dated in the future: not reachable by admission number
    create_prescription(
        id=PRESC_AGG_FUTURE,
        admissionNumber=ADMISSION,
        idPatient=1,
        date=now + timedelta(days=5),
        agg=True,
    )
    # conciliation: reachable by admission number through the conciliation query
    create_prescription(
        id=PRESC_CONCILIA,
        admissionNumber=ADMISSION,
        idPatient=1,
        date=now - timedelta(days=3),
        concilia="s",
    )
    # belongs to another admission: must never show up
    create_prescription(
        id=PRESC_OTHER_ADMISSION,
        admissionNumber=OTHER_ADMISSION,
        idPatient=2,
        date=now,
        agg=True,
    )

    yield

    session.execute(
        text("DELETE FROM demo.prescricao WHERE fkprescricao >= :first"),
        {"first": PRESC_AGG_TODAY},
    )
    session.execute(
        text("DELETE FROM demo.pessoa WHERE nratendimento = :admission"),
        {"admission": ADMISSION},
    )
    session_commit()


def _search(client, headers, term=None):
    """Call the endpoint, omitting the term entirely when it is None."""
    url = "/prescriptions/search"
    if term is not None:
        url = f"{url}?term={term}"

    return client.get(url, headers=headers)


def _ids(response):
    """Extract the returned prescription ids, preserving order."""
    return [item["idPrescription"] for item in response.get_json()["data"]]


def test_search_permission_denied(client):
    """A user without any of the search permissions gets [401 UNAUTHORIZED]."""
    headers = make_headers(get_access(client, roles=[Role.DISPENSING_MANAGER.value]))
    response = _search(client, headers, term=PRESC_AGG_TODAY)

    assert response.status_code == 401


def test_search_without_term(client, analyst_headers):
    """Omitting the term is rejected with [400 BAD REQUEST]."""
    response = _search(client, analyst_headers)

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.invalidParam"


def test_search_by_prescription_id(client, analyst_headers, seed_search_data):
    """A prescription id matches that prescription regardless of agg or date."""
    response = _search(client, analyst_headers, term=PRESC_REGULAR)

    assert response.status_code == 200
    assert _ids(response) == [str(PRESC_REGULAR)]


def test_search_by_prescription_id_returns_patient_data(
    client, analyst_headers, seed_search_data
):
    """The result carries the patient and department data joined to the prescription."""
    response = _search(client, analyst_headers, term=PRESC_AGG_TODAY)
    item = response.get_json()["data"][0]

    assert item["admissionNumber"] == ADMISSION
    assert item["agg"] is True
    assert item["concilia"] is None
    assert item["status"] == "0"
    assert item["type"] == "prescription"
    # dtnascimento is a date column, so it comes back without a time part
    assert item["birthdate"] == BIRTHDATE.date().isoformat()
    assert item["gender"] == "F"
    assert item["admissionDate"] == ADMISSION_DATE.isoformat()
    assert item["department"] == "Setor Adulto 1"
    assert item["date"] is not None


def test_search_by_admission_number(client, analyst_headers, seed_search_data):
    """An admission number returns the in-effect aggregated prescription and the
    conciliation, leaving out non-aggregated and future-dated ones."""
    response = _search(client, analyst_headers, term=ADMISSION)
    returned = _ids(response)

    assert response.status_code == 200
    assert set(returned) == {str(PRESC_AGG_TODAY), str(PRESC_CONCILIA)}
    assert str(PRESC_REGULAR) not in returned
    assert str(PRESC_AGG_FUTURE) not in returned


def test_search_by_admission_number_ordering(client, analyst_headers, seed_search_data):
    """The regular prescription is listed before the conciliation."""
    response = _search(client, analyst_headers, term=ADMISSION)
    data = response.get_json()["data"]

    assert data[0]["idPrescription"] == str(PRESC_AGG_TODAY)
    assert data[0]["concilia"] is None
    assert data[1]["idPrescription"] == str(PRESC_CONCILIA)
    assert data[1]["concilia"] == "s"


def test_search_does_not_leak_other_admissions(
    client, analyst_headers, seed_search_data
):
    """Prescriptions of a different admission are never returned."""
    response = _search(client, analyst_headers, term=ADMISSION)

    assert str(PRESC_OTHER_ADMISSION) not in _ids(response)


def test_search_no_match(client, analyst_headers, seed_search_data):
    """A term that matches nothing returns an empty list [200 OK]."""
    response = _search(client, analyst_headers, term=999999999)

    assert response.status_code == 200
    assert response.get_json()["data"] == []


def test_search_discharge_summary_permission(client, seed_search_data):
    """READ_DISCHARGE_SUMMARY alone is enough to search prescriptions."""
    headers = make_headers(get_access(client, roles=[Role.DISCHARGE_MANAGER.value]))
    response = _search(client, headers, term=PRESC_AGG_TODAY)

    assert response.status_code == 200
    assert _ids(response) == [str(PRESC_AGG_TODAY)]


def test_search_regulation_permission_skips_prescriptions(client, seed_search_data):
    """READ_REGULATION grants access to the endpoint but not to prescriptions."""
    headers = make_headers(get_access(client, roles=[Role.REGULATOR.value]))
    response = _search(client, headers, term=PRESC_AGG_TODAY)

    assert response.status_code == 200
    # no prescription results, and no regulation results either since the
    # REGULATION feature is not enabled for the test schema
    assert response.get_json()["data"] == []
