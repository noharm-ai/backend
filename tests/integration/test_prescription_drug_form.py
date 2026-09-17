"""Tests: dispensation form update (PUT /prescriptions/drug/form)

The endpoint the dispensation screen calls to store the pharmacy form of one or
more prescribed drugs. The payload is a map of prescription-drug id to the form
payload, and each entry is gated twice: by the WRITE_DISPENSATION permission
and by the caller's authorization on the drug's segment.

The whole map is written inside a single request transaction, so a rejected
entry has to leave the entries beside it untouched.
"""

from datetime import datetime

import pytest

from models.prescription import PrescriptionDrug
from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)

URL = "/prescriptions/drug/form"

# demo user 1 is authorized on segments 1 and 2 only (public.usuario_autorizacao),
# and the demo schema runs with AUTHORIZATION_SEGMENT on
AUTHORIZED_SEGMENT = 1
UNAUTHORIZED_SEGMENT = 99

# presmed ids the endpoint will never find
UNKNOWN_PD_ID = 100999999

A_FORM = {"tp": "capsula", "quantidade": 2}


@pytest.fixture
def dispensing_headers(client):
    """Headers with DISPENSING_MANAGER role — the role holding WRITE_DISPENSATION"""
    return make_headers(get_access(client, roles=[Role.DISPENSING_MANAGER.value]))


def _create_drug(id_segment=AUTHORIZED_SEGMENT, form=None):
    """Create a prescription holding one drug and return that drug's id.

    The segment is written with an UPDATE because the presmed BEFORE INSERT
    trigger recomputes idsegmento from the department, which would pull an
    unauthorized segment back to the seeded one.
    """
    id_prescription = test_counters["id_prescription"]
    admission_number = test_counters["admission_number"]
    test_counters["id_prescription"] += 1
    test_counters["admission_number"] += 1

    create_prescription(
        id=id_prescription,
        admissionNumber=admission_number,
        idPatient=1,
    )
    drug = create_prescription_drug(
        id=int(f"{id_prescription}001"),
        idPrescription=id_prescription,
        idDrug=3,
    )

    drug.idSegment = id_segment
    if form is not None:
        drug.form = form
    session_commit()

    return drug.id


def _reload(id_prescription_drug) -> PrescriptionDrug:
    """Read a prescription drug back from the database, ignoring the test session cache"""
    session.expire_all()
    return (
        session.query(PrescriptionDrug)
        .filter(PrescriptionDrug.id == id_prescription_drug)
        .first()
    )


def test_update_form_stores_the_payload(client, dispensing_headers):
    """PUT /prescriptions/drug/form - grava o form do medicamento prescrito"""
    id_pd = _create_drug()

    response = client.put(URL, json={str(id_pd): A_FORM}, headers=dispensing_headers)

    assert response.status_code == 200
    assert response.get_json()["data"] is True

    updated = _reload(id_pd)
    assert updated.form == A_FORM
    assert updated.user == 1
    assert updated.update is not None


def test_update_form_records_the_author_and_moment(client, dispensing_headers):
    """The write stamps the caller and the update timestamp on the row"""
    id_pd = _create_drug()
    before = datetime.today()

    response = client.put(URL, json={str(id_pd): A_FORM}, headers=dispensing_headers)

    assert response.status_code == 200

    updated = _reload(id_pd)
    assert updated.user == 1
    assert updated.update >= before.replace(microsecond=0)


def test_update_form_writes_every_entry_of_the_payload(client, dispensing_headers):
    """A payload with several drugs updates each one of them"""
    first = _create_drug()
    second = _create_drug()

    response = client.put(
        URL,
        json={str(first): {"tp": "comprimido"}, str(second): {"tp": "gotas"}},
        headers=dispensing_headers,
    )

    assert response.status_code == 200
    assert _reload(first).form == {"tp": "comprimido"}
    assert _reload(second).form == {"tp": "gotas"}


def test_update_form_overwrites_a_previous_form(client, dispensing_headers):
    """The stored form is replaced, not merged, so a stale key does not survive"""
    id_pd = _create_drug(form={"tp": "capsula", "obsoleto": True})

    response = client.put(
        URL, json={str(id_pd): {"tp": "comprimido"}}, headers=dispensing_headers
    )

    assert response.status_code == 200
    assert _reload(id_pd).form == {"tp": "comprimido"}


def test_update_form_accepts_a_null_form(client, dispensing_headers):
    """Sending null clears the form of a drug that had one"""
    id_pd = _create_drug(form=A_FORM)

    response = client.put(URL, json={str(id_pd): None}, headers=dispensing_headers)

    assert response.status_code == 200
    assert _reload(id_pd).form is None


def test_update_form_accepts_an_empty_payload(client, dispensing_headers):
    """An empty map is a no-op rather than an error"""
    response = client.put(URL, json={}, headers=dispensing_headers)

    assert response.status_code == 200
    assert response.get_json()["data"] is True


def test_update_form_rejects_an_unknown_drug(client, dispensing_headers):
    """An id with no presmed row behind it is a validation error"""
    response = client.put(
        URL, json={str(UNKNOWN_PD_ID): A_FORM}, headers=dispensing_headers
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.invalidRegister"


def test_update_form_rejects_an_unauthorized_segment(client, dispensing_headers):
    """A drug on a segment the caller is not authorized on cannot be written"""
    id_pd = _create_drug(id_segment=UNAUTHORIZED_SEGMENT)

    response = client.put(URL, json={str(id_pd): A_FORM}, headers=dispensing_headers)

    assert response.status_code == 401
    assert response.get_json()["code"] == "errors.businessRules"
    assert _reload(id_pd).form is None


def test_update_form_discards_the_whole_payload_when_one_entry_fails(
    client, dispensing_headers
):
    """A rejected entry rolls back the entries already written in the same request"""
    valid = _create_drug()

    response = client.put(
        URL,
        json={str(valid): A_FORM, str(UNKNOWN_PD_ID): A_FORM},
        headers=dispensing_headers,
    )

    assert response.status_code == 400
    assert _reload(valid).form is None


def test_update_form_requires_write_dispensation_permission(client, analyst_headers):
    """A PRESCRIPTION_ANALYST holds no WRITE_DISPENSATION, so the write is denied"""
    id_pd = _create_drug()

    response = client.put(URL, json={str(id_pd): A_FORM}, headers=analyst_headers)

    assert response.status_code == 401
    assert _reload(id_pd).form is None
