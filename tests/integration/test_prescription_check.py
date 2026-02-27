"""Tests: Prescription Check related operations"""

from datetime import datetime
from unittest.mock import patch

from tests.conftest import session, session_commit
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

import services.prescription_check_service as prescription_check_service
from models.enums import DrugTypeEnum, PrescriptionAuditTypeEnum
from models.prescription import Prescription, PrescriptionAudit, PrescriptionDrug
from static import prescalc
from tests.utils import utils_test_prescription
from tests.utils.utils_test_prescription import (
    create_basic_prescription,
    create_prescription,
    create_prescription_drug,
    test_counters,
)

CHECK_URL = "/prescriptions/status"
PRESCRIPTION = "20"


def _check_payload(id_prescription, status="s"):
    return {
        "idPrescription": id_prescription,
        "status": status,
        "evaluationTime": 0,
        "alerts": [],
        "fastCheck": False,
    }


def test_check_prescription_sets_status(client, analyst_headers):
    """Check prescription: sets prescription status to 's'"""
    prescription = create_basic_prescription()
    id_pres = prescription.id

    response = client.post(
        CHECK_URL, json=_check_payload(id_pres), headers=analyst_headers
    )

    assert response.status_code == 200

    session.expire_all()
    p = session.query(Prescription).filter(Prescription.id == id_pres).first()
    assert p.status == "s"


def test_check_prescription_sets_checado_on_active_drugs(client, analyst_headers):
    """Check prescription: sets checado=true on all active presmed rows"""
    prescription = create_basic_prescription()
    id_pres = prescription.id

    response = client.post(
        CHECK_URL, json=_check_payload(id_pres), headers=analyst_headers
    )

    assert response.status_code == 200

    session.expire_all()
    drugs = (
        session.query(PrescriptionDrug)
        .filter(PrescriptionDrug.idPrescription == id_pres)
        .filter(PrescriptionDrug.suspendedDate == None)
        .all()
    )

    assert len(drugs) > 0
    for drug in drugs:
        assert drug.checked is True


def test_check_prescription_audit_total_itens_excludes_diet(client, analyst_headers):
    """Check prescription: audit totalItens counts only DRUG/SOLUTION/PROCEDURE, not DIET.
    checkedindex receives all non-suspended rows regardless of type."""

    id_pres = test_counters["id_prescription"]
    admission = test_counters["admission_number"]

    create_prescription(id=id_pres, admissionNumber=admission, idPatient=1)

    # 2 DRUG + 1 SOLUTION + 1 PROCEDURE = 4 countable items
    create_prescription_drug(
        id=int(f"{id_pres}001"),
        idPrescription=id_pres,
        idDrug=1,
        source=DrugTypeEnum.DRUG.value,
    )
    create_prescription_drug(
        id=int(f"{id_pres}002"),
        idPrescription=id_pres,
        idDrug=2,
        source=DrugTypeEnum.DRUG.value,
    )
    create_prescription_drug(
        id=int(f"{id_pres}003"),
        idPrescription=id_pres,
        idDrug=3,
        source=DrugTypeEnum.SOLUTION.value,
    )
    create_prescription_drug(
        id=int(f"{id_pres}004"),
        idPrescription=id_pres,
        idDrug=4,
        source=DrugTypeEnum.PROCEDURE.value,
    )
    # 1 DIET — must NOT be counted in totalItens but IS written to checkedindex
    create_prescription_drug(
        id=int(f"{id_pres}005"),
        idPrescription=id_pres,
        idDrug=5,
        source=DrugTypeEnum.DIET.value,
    )

    test_counters["id_prescription"] += 1
    test_counters["admission_number"] += 1

    response = client.post(
        CHECK_URL, json=_check_payload(id_pres), headers=analyst_headers
    )

    assert response.status_code == 200

    session.expire_all()

    # Audit record must count only the 3 valid drug types (4 items)
    audit = (
        session.query(PrescriptionAudit)
        .filter(PrescriptionAudit.idPrescription == id_pres)
        .filter(PrescriptionAudit.auditType == PrescriptionAuditTypeEnum.CHECK.value)
        .first()
    )
    assert audit is not None
    assert audit.totalItens == 4

    # checkedindex must contain all 5 non-suspended rows (no source filter)
    result = session.execute(
        text("SELECT COUNT(*) FROM demo.checkedindex WHERE fkprescricao = :id"),
        {"id": id_pres},
    )
    assert result.scalar() == 5


def test_check_prescription_skips_suspended_drugs(client, analyst_headers):
    """Check prescription: does not set checado on suspended presmed rows"""

    id_pres = test_counters["id_prescription"]
    admission = test_counters["admission_number"]

    create_prescription(
        id=id_pres,
        admissionNumber=admission,
        idPatient=1,
    )

    id_active = int(f"{id_pres}001")
    id_suspended = int(f"{id_pres}002")

    create_prescription_drug(id=id_active, idPrescription=id_pres, idDrug=3)
    create_prescription_drug(id=id_suspended, idPrescription=id_pres, idDrug=44)

    # Set dtsuspensao via raw SQL — the ORM insert does not reliably persist it (because of the trigger)
    session.execute(
        text("UPDATE demo.presmed SET dtsuspensao = :dt WHERE fkpresmed = :id"),
        {"dt": datetime.now(), "id": id_suspended},
    )
    session_commit()

    test_counters["id_prescription"] += 1
    test_counters["admission_number"] += 1

    response = client.post(
        CHECK_URL, json=_check_payload(id_pres), headers=analyst_headers
    )

    assert response.status_code == 200

    session.expire_all()
    suspended = (
        session.query(PrescriptionDrug)
        .filter(PrescriptionDrug.id == id_suspended)
        .first()
    )
    assert suspended.checked is not True


def test_check_prescription_already_checked_returns_error(client, analyst_headers):
    """Check prescription: returns 400 when prescription is already checked"""

    prescription = create_basic_prescription()
    id_pres = prescription.id

    # First check
    client.post(CHECK_URL, json=_check_payload(id_pres), headers=analyst_headers)

    # Second check on already-checked prescription
    response = client.post(
        CHECK_URL, json=_check_payload(id_pres), headers=analyst_headers
    )

    assert response.status_code == 400


def test_uncheck_preserves_checado(client, analyst_headers):
    """Uncheck prescription: checado flag on presmed rows is preserved after unchecking"""

    prescription = create_basic_prescription()
    id_pres = prescription.id

    # Check first
    client.post(
        CHECK_URL, json=_check_payload(id_pres, status="s"), headers=analyst_headers
    )

    # Then uncheck
    response = client.post(
        CHECK_URL, json=_check_payload(id_pres, status="0"), headers=analyst_headers
    )

    assert response.status_code == 200

    session.expire_all()
    p = session.query(Prescription).filter(Prescription.id == id_pres).first()
    assert p.status == "0"

    drugs = (
        session.query(PrescriptionDrug)
        .filter(PrescriptionDrug.idPrescription == id_pres)
        .filter(PrescriptionDrug.suspendedDate == None)
        .all()
    )

    assert len(drugs) > 0
    for drug in drugs:
        assert drug.checked is True


def test_check_prescription_viewer_unauthorized(client, viewer_headers):
    """Teste put /prescriptions/status - Assegura que o usuário VIEWER não tenha autorização."""
    response = client.post(
        CHECK_URL,
        json={"status": "s", "idPrescription": PRESCRIPTION},
        headers=viewer_headers,
    )

    assert response.status_code == 401


def test_check_aggregate_prescription(client, analyst_headers):
    """Teste put /prescriptions/status - Verifica o status 's' e audit para prescrição agregada e as prescrições dentro dela."""
    id = 2012301000000003
    admissionNumber = 3
    prescriptionid1 = 4
    prescriptionid2 = 7

    utils_test_prescription.prepare_test_aggregate(
        id, admissionNumber, prescriptionid1, prescriptionid2
    )

    # Recreate the aggregate prescription
    prescalc(
        {"schema": "demo", "id_prescription": prescriptionid1, "force": True},
        None,
    )

    # Check the aggregate prescription
    client.post(
        CHECK_URL,
        json={"status": "s", "idPrescription": id},
        headers=analyst_headers,
    )

    pInAg = (
        session.query(Prescription)
        .filter(Prescription.id.in_([prescriptionid1, id]))
        .filter(Prescription.status == "s")
        .all()
    )
    pOutAg = (
        session.query(Prescription)
        .filter(Prescription.id == prescriptionid2)
        .filter(Prescription.status == "0")
        .first()
    )
    pInAgaudit = (
        session.query(PrescriptionAudit)
        .filter(PrescriptionAudit.idPrescription.in_([prescriptionid1, id]))
        .filter(PrescriptionAudit.auditType == 1)
        .all()
    )
    pOutAgaudit = (
        session.query(PrescriptionAudit)
        .filter(PrescriptionAudit.idPrescription == prescriptionid2)
        .filter(PrescriptionAudit.auditType == 1)
        .first()
    )

    assert pOutAg
    assert len(pInAg) == 2
    assert len(pInAgaudit) == 2
    assert not pOutAgaudit


def test_check_prescription_retries_on_deadlock(client, analyst_headers):
    """check_prescription: recovers transparently from a single deadlock on presmed UPDATE"""
    prescription = create_basic_prescription()
    id_pres = prescription.id

    call_count = {"n": 0}
    original = prescription_check_service._add_checkedindex

    def flaky(prescription, user):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise OperationalError("deadlock detected", None, None)
        return original(prescription=prescription, user=user)

    with patch(
        "services.prescription_check_service._add_checkedindex", side_effect=flaky
    ):
        response = client.post(
            CHECK_URL, json=_check_payload(id_pres), headers=analyst_headers
        )

    assert response.status_code == 200
    assert call_count["n"] == 2  # first call deadlocked, second succeeded on retry

    session.expire_all()
    p = session.query(Prescription).filter(Prescription.id == id_pres).first()
    assert p.status == "s"


def test_check_prescription_fails_after_max_retries(client, analyst_headers):
    """check_prescription: returns 500 and leaves prescription unchanged when deadlock persists across all retries"""
    prescription = create_basic_prescription()
    id_pres = prescription.id

    with patch(
        "services.prescription_check_service._add_checkedindex",
        side_effect=OperationalError("deadlock detected", None, None),
    ):
        response = client.post(
            CHECK_URL, json=_check_payload(id_pres), headers=analyst_headers
        )

    assert response.status_code == 500

    session.expire_all()
    p = session.query(Prescription).filter(Prescription.id == id_pres).first()
    assert p.status == "0"  # rollback preserved the original status
