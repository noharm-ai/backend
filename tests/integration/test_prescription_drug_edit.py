"""Tests: Prescription drug edit operations (services.prescription_drug_edit_service).

Covers the /editPrescription/drug* CRUD endpoints: create, update, suspend/unsuspend,
and the "missing drugs" discovery/copy flow that fills a prescription with drugs that
were prescribed on other prescriptions of the same admission.
"""

from datetime import datetime, timedelta

from mobile import app as flask_app
from tests.conftest import session
from tests.utils.utils_test_prescription import (
    create_basic_prescription,
    create_prescription,
    create_prescription_drug,
    test_counters,
)

import services.prescription_drug_edit_service as edit_service
from models.prescription import PrescriptionDrug


def _next_ids():
    """Reserve a unique prescription id and admission number for a test."""
    id_prescription = test_counters["id_prescription"]
    admission_number = test_counters["admission_number"]
    test_counters["id_prescription"] += 1
    test_counters["admission_number"] += 1
    return id_prescription, admission_number


def _prescription_with_one_drug(id_drug=3):
    """Create a prescription holding a single drug.

    The drug's presmed id ends in ``500`` so it never collides with getNextId,
    which mints new ids as ``concat(prescription_id, lpad(count, 3))``.
    """
    id_prescription, admission = _next_ids()
    create_prescription(id=id_prescription, admissionNumber=admission, idPatient=1)
    create_prescription_drug(
        id=int(f"{id_prescription}500"),
        idPrescription=id_prescription,
        idDrug=id_drug,
    )
    return id_prescription


def test_get_next_id_appends_sequence(client, analyst_headers):  # noqa: ARG001
    """getNextId concatenates the prescription id with the zero-padded drug count."""
    prescription = create_basic_prescription()

    # create_basic_prescription adds exactly two drugs
    with flask_app.app_context():
        next_id = edit_service.getNextId(prescription.id, "demo")

    assert next_id == f"{prescription.id}002"


def test_create_prescription_drug(client, analyst_headers):
    """POST /editPrescription/drug creates a new presmed row and returns it."""
    id_prescription = _prescription_with_one_drug()

    payload = {
        "idPrescription": id_prescription,
        "idDrug": 5,
        "source": "Medicamentos",
        "dose": 42.0,
        "measureUnit": "1",
        "frequency": "1",
        "interval": "8h",
        "route": "IV",
        "recommendation": "test recommendation",
    }

    response = client.post(
        "/editPrescription/drug", json=payload, headers=analyst_headers
    )

    assert response.status_code == 200

    session.expire_all()
    created = (
        session.query(PrescriptionDrug)
        .filter(PrescriptionDrug.idPrescription == id_prescription)
        .filter(PrescriptionDrug.idDrug == 5)
        .first()
    )
    assert created is not None
    assert created.dose == 42.0
    assert created.route == "IV"
    assert created.notes == "test recommendation"


def test_update_prescription_drug(client, analyst_headers):
    """PUT /editPrescription/drug/<id> updates only the supplied fields."""
    prescription = create_basic_prescription()
    id_pd = int(f"{prescription.id}001")

    payload = {"dose": 999.0, "route": "SC", "recommendation": "updated"}

    response = client.put(
        f"/editPrescription/drug/{id_pd}", json=payload, headers=analyst_headers
    )

    assert response.status_code == 200

    session.expire_all()
    updated = session.query(PrescriptionDrug).get(id_pd)
    assert updated.dose == 999.0
    assert updated.route == "SC"
    assert updated.notes == "updated"


def test_update_prescription_drug_not_found(client, analyst_headers):
    """Updating a non-existent presmed row returns a 400 validation error."""
    response = client.put(
        "/editPrescription/drug/100999999",
        json={"dose": 1.0},
        headers=analyst_headers,
    )

    assert response.status_code == 400


def test_toggle_prescription_drug_suspension(client, analyst_headers):
    """PUT .../suspend/1 sets suspendedDate; .../suspend/0 clears it."""
    prescription = create_basic_prescription()
    id_pd = int(f"{prescription.id}001")

    # suspend
    response = client.put(
        f"/editPrescription/drug/{id_pd}/suspend/1", headers=analyst_headers
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["suspended"] is True

    session.expire_all()
    assert session.query(PrescriptionDrug).get(id_pd).suspendedDate is not None

    # unsuspend
    response = client.put(
        f"/editPrescription/drug/{id_pd}/suspend/0", headers=analyst_headers
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["suspended"] is False

    session.expire_all()
    assert session.query(PrescriptionDrug).get(id_pd).suspendedDate is None


def test_get_missing_drugs(client, analyst_headers):
    """GET .../missing-drugs lists active drugs of the admission absent on this prescription."""
    id_a, admission = _next_ids()
    id_b, _ = _next_ids()

    # Two prescriptions on the same admission
    create_prescription(id=id_a, admissionNumber=admission, idPatient=1)
    create_prescription(id=id_b, admissionNumber=admission, idPatient=1)

    # Prescription A has drug 3; prescription B has drug 4
    create_prescription_drug(
        id=int(f"{id_a}001"), idPrescription=id_a, idDrug=3
    )
    create_prescription_drug(
        id=int(f"{id_b}001"), idPrescription=id_b, idDrug=4
    )

    response = client.get(
        f"/editPrescription/{id_a}/missing-drugs", headers=analyst_headers
    )

    assert response.status_code == 200

    missing = response.get_json()["data"]
    missing_ids = [d["idDrug"] for d in missing]

    # drug 4 (only on B) is missing from A; drug 3 (already on A) is not listed
    assert 4 in missing_ids
    assert 3 not in missing_ids


def test_get_missing_drugs_not_found(client, analyst_headers):
    """Missing-drugs on a non-existent prescription returns a 400 validation error."""
    response = client.get(
        "/editPrescription/100999999/missing-drugs", headers=analyst_headers
    )

    assert response.status_code == 400


def test_copy_missing_drugs(client, analyst_headers):
    """POST .../missing-drugs/copy duplicates selected drugs onto the target prescription."""
    id_a, admission = _next_ids()
    id_b, _ = _next_ids()

    create_prescription(id=id_a, admissionNumber=admission, idPatient=1)
    create_prescription(id=id_b, admissionNumber=admission, idPatient=1)

    # A needs at least one drug so getNextId can compute the next sequence.
    # Its presmed id ends in 500 to avoid colliding with the minted copy id.
    create_prescription_drug(id=int(f"{id_a}500"), idPrescription=id_a, idDrug=3)
    create_prescription_drug(id=int(f"{id_b}001"), idPrescription=id_b, idDrug=4)

    response = client.post(
        f"/editPrescription/{id_a}/missing-drugs/copy",
        json={"idDrugs": [4]},
        headers=analyst_headers,
    )

    assert response.status_code == 200

    session.expire_all()
    copied = (
        session.query(PrescriptionDrug)
        .filter(PrescriptionDrug.idPrescription == id_a)
        .filter(PrescriptionDrug.idDrug == 4)
        .first()
    )
    assert copied is not None


def test_copy_missing_drugs_empty_selection(client, analyst_headers):
    """Copying with no selected drugs returns a 400 validation error."""
    id_a, admission = _next_ids()
    create_prescription(id=id_a, admissionNumber=admission, idPatient=1)

    response = client.post(
        f"/editPrescription/{id_a}/missing-drugs/copy",
        json={"idDrugs": []},
        headers=analyst_headers,
    )

    assert response.status_code == 400


def test_create_prescription_drug_requires_write_permission(client, viewer_headers):
    """A read-only VIEWER cannot create a prescription drug (401)."""
    prescription = create_basic_prescription()

    payload = {
        "idPrescription": prescription.id,
        "idDrug": 5,
        "source": "Medicamentos",
        "dose": 10.0,
    }

    response = client.post(
        "/editPrescription/drug", json=payload, headers=viewer_headers
    )

    assert response.status_code == 401
