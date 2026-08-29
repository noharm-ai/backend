"""Tests: GET /reports/drug-attributes/history and /reports/antimicrobial/history

The report lists every prescribed drug flagged with a given attribute for one
admission. Three things carry the business risk and are pinned down here:

* the ``attribute`` query param is mapped to a column name that is interpolated
  straight into the SQL, so only the keys of ``VALID_ATTRIBUTES`` may pass and
  each key must select the column it claims to;
* the report widens the search to the patient's two previous admissions, so a
  readmitted patient keeps the history of what was already given;
* ``/reports/antimicrobial/history`` is the legacy alias kept for clients that
  have not migrated, and must stay equivalent to ``attribute=antimicro``.

Seed data used (demo schema, medatributos on segment 1):

* admission 5 / patient 5 — prescription 8 (presmed 10, ENALAPRIL, antimicro)
  and prescription 20 (presmed 30, ENALAPRIL, antimicro; presmed 42, BISACODIL,
  controlados).
"""

import pytest
from sqlalchemy import text

from tests.conftest import session, session_commit
from utils import status

URL = "/reports/drug-attributes/history"
LEGACY_URL = "/reports/antimicrobial/history"

# seed admission/patient carrying the flagged prescription drugs
ADMISSION = 5
PATIENT_ID = 5

# seed presmed ids reachable from ADMISSION
ANTIMICRO_DRUGS = {"10", "30"}  # ENALAPRIL, on prescriptions 8 and 20
CONTROLLED_DRUG = "42"  # BISACODIL, on prescription 20

# a later admission for the same patient, created by one test to exercise the
# previous-admission lookup. Ids >= 100000 are wiped by the session-scoped
# clean_test_artifacts fixture in tests/conftest.py.
LATER_ADMISSION = 100005


def _get(client, headers, admission_number=ADMISSION, attribute=None, url=URL):
    """Call the report, omitting `attribute` when it is None."""
    params = {}
    if admission_number is not None:
        params["admissionNumber"] = admission_number
    if attribute is not None:
        params["attribute"] = attribute

    return client.get(url, query_string=params, headers=headers)


def _drug_ids(response):
    """Return the idPrescriptionDrug values of a successful response."""
    return {row["idPrescriptionDrug"] for row in response.get_json()["data"]}


@pytest.fixture
def later_admission():
    """Register a second, more recent admission for the seed patient."""
    session.execute(
        text(
            "INSERT INTO demo.pessoa (fkpessoa, nratendimento, dtinternacao) "
            "VALUES (:patient, :admission, '2024-01-05 00:00:00')"
        ),
        {"patient": PATIENT_ID, "admission": LATER_ADMISSION},
    )
    session_commit()

    yield LATER_ADMISSION

    session.execute(
        text("DELETE FROM demo.pessoa WHERE nratendimento = :admission"),
        {"admission": LATER_ADMISSION},
    )
    session.execute(
        text("DELETE FROM demo.pessoa_audit WHERE nratendimento = :admission"),
        {"admission": LATER_ADMISSION},
    )
    session_commit()


def test_history_requires_read_reports(client, navigator_headers):
    """GET /reports/drug-attributes/history - 401 without READ_REPORTS"""
    response = _get(client, navigator_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_history_requires_admission_number(client, analyst_headers):
    """GET /reports/drug-attributes/history - 400 when admissionNumber is missing"""
    response = _get(client, analyst_headers, admission_number=None)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidParams"


def test_history_rejects_unknown_attribute(client, analyst_headers):
    """GET /reports/drug-attributes/history - 400 for an attribute outside the allowlist"""
    response = _get(client, analyst_headers, attribute="naopadronizado")

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    body = response.get_json()
    assert body["code"] == "errors.invalidParams"
    # the message lists the accepted keys so the caller can fix the request
    assert "notdefault" in body["message"]


def test_history_rejects_sql_injection_attempt(client, analyst_headers):
    """GET /reports/drug-attributes/history - a crafted attribute never reaches the SQL"""
    response = _get(client, analyst_headers, attribute="antimicro OR TRUE --")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidParams"


def test_history_defaults_to_antimicro(client, analyst_headers):
    """GET /reports/drug-attributes/history - omitting attribute reports antimicrobials"""
    response = _get(client, analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    assert _drug_ids(response) == ANTIMICRO_DRUGS


def test_history_returns_prescription_details(client, analyst_headers):
    """GET /reports/drug-attributes/history - each row carries the prescription context"""
    response = _get(client, analyst_headers, attribute="antimicro")

    assert response.status_code == status.HTTP_200_OK

    rows = {row["idPrescriptionDrug"]: row for row in response.get_json()["data"]}
    row = rows["10"]

    assert row["idPrescription"] == "8"
    assert row["admissionNumber"] == ADMISSION
    assert row["prescriptionDate"].startswith("2020-12-31")
    assert row["drug"] == "ENALAPRIL 20 mg CP"
    assert row["dose"] == 20
    assert row["measureUnit"] == "mg"
    assert row["frequency"] == "12h/12h"
    assert row["route"] == "VO"
    # nothing was suspended on the seed prescription
    assert row["suspensionDate"] is None


def test_history_selects_the_column_of_the_requested_attribute(
    client, analyst_headers
):
    """GET /reports/drug-attributes/history - 'controlled' reads the controlados column"""
    response = _get(client, analyst_headers, attribute="controlled")

    assert response.status_code == status.HTTP_200_OK

    ids = _drug_ids(response)
    assert ids == {CONTROLLED_DRUG}
    # the antimicrobials must not leak into a different attribute's report
    assert not ids & ANTIMICRO_DRUGS


def test_history_is_empty_when_no_drug_carries_the_attribute(client, analyst_headers):
    """GET /reports/drug-attributes/history - an unused attribute returns an empty list"""
    response = _get(client, analyst_headers, attribute="chemo")

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == []


def test_history_is_empty_for_an_unknown_admission(client, analyst_headers):
    """GET /reports/drug-attributes/history - an admission with no prescriptions is empty"""
    response = _get(client, analyst_headers, admission_number=987654)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == []


def test_history_includes_previous_admissions_of_the_patient(
    client, analyst_headers, later_admission
):
    """GET /reports/drug-attributes/history - a readmission keeps the earlier history"""
    response = _get(client, analyst_headers, admission_number=later_admission)

    assert response.status_code == status.HTTP_200_OK

    rows = response.get_json()["data"]
    assert {row["idPrescriptionDrug"] for row in rows} == ANTIMICRO_DRUGS
    # the rows belong to the previous admission, not to the one asked for
    assert {row["admissionNumber"] for row in rows} == {ADMISSION}


def test_legacy_route_matches_the_antimicro_report(client, analyst_headers):
    """GET /reports/antimicrobial/history - the legacy alias still reports antimicrobials"""
    legacy = _get(client, analyst_headers, url=LEGACY_URL)
    current = _get(client, analyst_headers, attribute="antimicro")

    assert legacy.status_code == status.HTTP_200_OK
    assert _drug_ids(legacy) == _drug_ids(current) == ANTIMICRO_DRUGS


def test_legacy_route_requires_admission_number(client, analyst_headers):
    """GET /reports/antimicrobial/history - 400 when admissionNumber is missing"""
    response = _get(client, analyst_headers, admission_number=None, url=LEGACY_URL)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidParams"
