"""Integration tests for GET /prescriptions/<idPrescription>/integration-errors

The release of a checked prescription to the origin system is asynchronous.
When it fails, the only trace is an ERROR_INTEGRATION_PRESCRIPTION_RELEASE row
in prescricao_audit. This endpoint exposes the errors that are still pending so
the screening page can warn the user.

Covers:
- Authorization and permissions
- Checked prescription with and without a pending error
- Errors already retried by a new check
- Unchecked prescriptions (a release was never sent)
- Aggregated prescriptions (errors of the internal prescriptions)
"""

from datetime import datetime, timedelta

from sqlalchemy import text

from models.enums import DrugTypeEnum, PrescriptionAuditTypeEnum
from models.prescription import PrescriptionAudit
from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)

# Seed prescription already in the test database (from noharm-ai/database fixtures)
SEED_PRESCRIPTION_ID = "20"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mark_as_checked(id_prescription: int):
    """Set the prescription status to checked after the drugs are in place."""
    session.execute(
        text("UPDATE demo.prescricao SET status = 's' WHERE fkprescricao = :id"),
        {"id": id_prescription},
    )
    session_commit()


def _audit(prescription, audit_type: PrescriptionAuditTypeEnum, created_at, extra=None):
    """Write a prescricao_audit row for the given prescription."""
    audit = PrescriptionAudit()
    audit.auditType = audit_type.value
    audit.admissionNumber = prescription.admissionNumber
    audit.idPrescription = prescription.id
    audit.prescriptionDate = prescription.date
    audit.idDepartment = prescription.idDepartment
    audit.idSegment = prescription.idSegment
    audit.totalItens = 0
    audit.agg = prescription.agg
    audit.bed = prescription.bed
    audit.extra = extra
    audit.createdAt = created_at
    audit.createdBy = 1

    session.add(audit)
    session_commit()

    return audit


def _create_prescription(agg: bool = None, admission_number: int = None, checked=True):
    """Create a prescription with one drug and return it."""
    id_pres = test_counters["id_prescription"]
    adm = admission_number or test_counters["admission_number"]

    prescription = create_prescription(
        id=id_pres,
        admissionNumber=adm,
        idPatient=1,
        agg=agg,
        date=datetime.now(),
        expire=datetime.now() + timedelta(days=1),
    )
    create_prescription_drug(
        id=int(f"{id_pres}001"),
        idPrescription=id_pres,
        idDrug=3,
        source=DrugTypeEnum.DRUG.value,
    )
    test_counters["id_prescription"] += 1
    test_counters["admission_number"] += 1

    if checked:
        _mark_as_checked(id_pres)

    return prescription


def _get_errors(client, headers, id_prescription, id_prescription_list=None):
    url = f"/prescriptions/{id_prescription}/integration-errors"
    if id_prescription_list:
        url += "?idPrescriptionList=" + ",".join(str(i) for i in id_prescription_list)

    response = client.get(url, headers=headers)
    assert response.status_code == 200

    return response.get_json()["data"]


# ===========================================================================
# Group 1 - Authorization
# ===========================================================================


def test_integration_errors_unauthenticated(client):
    """Request without auth headers must return HTTP 401."""
    response = client.get(f"/prescriptions/{SEED_PRESCRIPTION_ID}/integration-errors")
    assert response.status_code == 401


def test_integration_errors_permission_denied(client, user_manager_headers):
    """USER_MANAGER lacks READ_PRESCRIPTION -> must return 401."""
    response = client.get(
        f"/prescriptions/{SEED_PRESCRIPTION_ID}/integration-errors",
        headers=user_manager_headers,
    )
    assert response.status_code == 401


# ===========================================================================
# Group 2 - Pending release integration errors
# ===========================================================================


def test_integration_errors_invalid_prescription(client, analyst_headers):
    """A prescription that does not exist must return HTTP 400."""
    response = client.get(
        "/prescriptions/999999999/integration-errors", headers=analyst_headers
    )
    assert response.status_code == 400


def test_integration_errors_absent_when_nothing_failed(client, analyst_headers):
    """A checked prescription with no audit trail must report no integration error."""
    prescription = _create_prescription()

    assert _get_errors(client, analyst_headers, prescription.id) == []


def test_integration_error_is_reported(client, analyst_headers):
    """The last release error of a checked prescription is exposed."""
    prescription = _create_prescription()
    check_date = datetime.now() - timedelta(minutes=10)
    error_date = datetime.now() - timedelta(minutes=5)

    _audit(prescription, PrescriptionAuditTypeEnum.CHECK, check_date)
    _audit(
        prescription,
        PrescriptionAuditTypeEnum.ERROR_INTEGRATION_PRESCRIPTION_RELEASE,
        error_date,
        extra={"message": "timeout ao enviar a checagem"},
    )

    errors = _get_errors(client, analyst_headers, prescription.id)
    assert len(errors) == 1
    assert errors[0]["idPrescription"] == str(prescription.id)
    assert errors[0]["message"] == "timeout ao enviar a checagem"
    assert datetime.fromisoformat(errors[0]["date"]) == error_date
    assert errors[0]["extra"] == {"message": "timeout ao enviar a checagem"}


def test_integration_error_solved_by_a_new_check_is_ignored(client, analyst_headers):
    """An error followed by a new check event was retried and must not be reported."""
    prescription = _create_prescription()
    base_date = datetime.now() - timedelta(minutes=30)

    _audit(prescription, PrescriptionAuditTypeEnum.CHECK, base_date)
    _audit(
        prescription,
        PrescriptionAuditTypeEnum.ERROR_INTEGRATION_PRESCRIPTION_RELEASE,
        base_date + timedelta(minutes=5),
        extra={"message": "falha temporaria"},
    )
    _audit(
        prescription,
        PrescriptionAuditTypeEnum.CHECK,
        base_date + timedelta(minutes=10),
    )

    assert _get_errors(client, analyst_headers, prescription.id) == []


def test_integration_error_ignores_unrelated_audit_events(client, analyst_headers):
    """Events other than check/release error must not hide a pending error."""
    prescription = _create_prescription()
    base_date = datetime.now() - timedelta(minutes=30)

    _audit(prescription, PrescriptionAuditTypeEnum.CHECK, base_date)
    _audit(
        prescription,
        PrescriptionAuditTypeEnum.ERROR_INTEGRATION_PRESCRIPTION_RELEASE,
        base_date + timedelta(minutes=5),
    )
    _audit(
        prescription,
        PrescriptionAuditTypeEnum.REVISION,
        base_date + timedelta(minutes=10),
    )

    errors = _get_errors(client, analyst_headers, prescription.id)
    assert len(errors) == 1
    assert errors[0]["message"] is None


def test_integration_error_not_reported_when_prescription_is_not_checked(
    client, analyst_headers
):
    """An unchecked prescription never had a release: the error must not be reported."""
    prescription = _create_prescription(checked=False)

    _audit(
        prescription,
        PrescriptionAuditTypeEnum.ERROR_INTEGRATION_PRESCRIPTION_RELEASE,
        datetime.now(),
        extra={"message": "falha"},
    )

    assert _get_errors(client, analyst_headers, prescription.id) == []


def test_integration_error_of_internal_prescription_shows_on_the_agg(
    client, analyst_headers
):
    """The ids sent by the caller are inspected together with the agg prescription."""
    agg_prescription = _create_prescription(agg=True)
    internal_prescription = _create_prescription(
        admission_number=agg_prescription.admissionNumber
    )
    error_date = datetime.now() - timedelta(minutes=5)

    _audit(
        internal_prescription,
        PrescriptionAuditTypeEnum.ERROR_INTEGRATION_PRESCRIPTION_RELEASE,
        error_date,
        extra={"erro": "PEP indisponivel"},
    )

    errors = _get_errors(
        client,
        analyst_headers,
        agg_prescription.id,
        id_prescription_list=[internal_prescription.id],
    )
    assert len(errors) == 1
    assert errors[0]["idPrescription"] == str(internal_prescription.id)
    assert errors[0]["message"] == "PEP indisponivel"


def test_integration_error_ignores_ids_from_another_admission(
    client, analyst_headers
):
    """Ids come from the client: one outside this admission must report nothing."""
    prescription = _create_prescription()
    other_prescription = _create_prescription()

    _audit(
        other_prescription,
        PrescriptionAuditTypeEnum.ERROR_INTEGRATION_PRESCRIPTION_RELEASE,
        datetime.now(),
        extra={"message": "falha de outro atendimento"},
    )

    errors = _get_errors(
        client,
        analyst_headers,
        prescription.id,
        id_prescription_list=[other_prescription.id],
    )
    assert errors == []


def test_integration_errors_ignores_a_malformed_id_list(client, analyst_headers):
    """A non numeric idPrescriptionList must not break the request."""
    prescription = _create_prescription()

    response = client.get(
        f"/prescriptions/{prescription.id}/integration-errors?idPrescriptionList=abc",
        headers=analyst_headers,
    )
    assert response.status_code == 200
    assert response.get_json()["data"] == []
