"""Tests: Prescription Check related operations"""

import json
from datetime import datetime

from tests.conftest import get_access, make_headers, session, session_commit
from sqlalchemy import text

from models.enums import DrugTypeEnum, PrescriptionAuditTypeEnum
from models.prescription import Prescription, PrescriptionAudit, PrescriptionDrug
from security.role import Role
from tests.utils.utils_test_prescription import (
    create_basic_prescription,
    create_prescription,
    create_prescription_drug,
    test_counters,
)


def _check_url():
    return "/prescriptions/status"


def _check_payload(id_prescription, status="s"):
    return json.dumps(
        {
            "idPrescription": id_prescription,
            "status": status,
            "evaluationTime": 0,
            "alerts": [],
            "fastCheck": False,
        }
    )


def test_check_prescription_sets_status(client):
    """Check prescription: sets prescription status to 's'"""

    prescription = create_basic_prescription()
    id_pres = prescription.id

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.post(
        _check_url(),
        data=_check_payload(id_pres),
        headers=make_headers(access_token),
    )

    assert response.status_code == 200

    session.expire_all()
    p = session.query(Prescription).filter(Prescription.id == id_pres).first()
    assert p.status == "s"


def test_check_prescription_sets_checado_on_active_drugs(client):
    """Check prescription: sets checado=true on all active presmed rows"""

    prescription = create_basic_prescription()
    id_pres = prescription.id

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.post(
        _check_url(),
        data=_check_payload(id_pres),
        headers=make_headers(access_token),
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


def test_check_prescription_audit_total_itens_excludes_diet(client):
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

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.post(
        _check_url(),
        data=_check_payload(id_pres),
        headers=make_headers(access_token),
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


def test_check_prescription_skips_suspended_drugs(client):
    """Check prescription: does not set checado on suspended presmed rows"""

    id_pres = test_counters["id_prescription"]
    admission = test_counters["admission_number"]

    prescription = create_prescription(
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

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.post(
        _check_url(),
        data=_check_payload(id_pres),
        headers=make_headers(access_token),
    )

    assert response.status_code == 200

    session.expire_all()
    suspended = (
        session.query(PrescriptionDrug)
        .filter(PrescriptionDrug.id == id_suspended)
        .first()
    )
    assert suspended.checked is not True


def test_check_prescription_already_checked_returns_error(client):
    """Check prescription: returns 400 when prescription is already checked"""

    prescription = create_basic_prescription()
    id_pres = prescription.id

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    # First check
    client.post(
        _check_url(),
        data=_check_payload(id_pres),
        headers=make_headers(access_token),
    )

    # Second check on already-checked prescription
    response = client.post(
        _check_url(),
        data=_check_payload(id_pres),
        headers=make_headers(access_token),
    )

    assert response.status_code == 400


def test_uncheck_preserves_checado(client):
    """Uncheck prescription: checado flag on presmed rows is preserved after unchecking"""

    prescription = create_basic_prescription()
    id_pres = prescription.id

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    # Check first
    client.post(
        _check_url(),
        data=_check_payload(id_pres, status="s"),
        headers=make_headers(access_token),
    )

    # Then uncheck
    response = client.post(
        _check_url(),
        data=_check_payload(id_pres, status="0"),
        headers=make_headers(access_token),
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
