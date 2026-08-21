"""Tests: Prescription Check related operations"""

import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

from mobile import app as flask_app
from tests.conftest import session, session_commit
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

import services.prescription_check_service as prescription_check_service
from config import Config
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


@contextmanager
def _mock_presmed_dispatch(function_name="test-backend-function"):
    """Patch BACKEND_FUNCTION_NAME and the lambda client so tests can assert
    the async presmed 'checado' dispatch without touching AWS"""
    lambda_client = MagicMock()
    with patch.object(Config, "BACKEND_FUNCTION_NAME", function_name), patch(
        "services.prescription_check_service.aws.get_client",
        return_value=lambda_client,
    ):
        yield lambda_client


def _dispatched_payloads(lambda_client):
    """Return the decoded payloads of every lambda invoke performed"""
    return [
        json.loads(call.kwargs["Payload"])
        for call in lambda_client.invoke.call_args_list
    ]


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


def test_check_prescription_dispatches_presmed_event(client, analyst_headers):
    """Check prescription: dispatches an async event to mark presmed as
    checado instead of updating presmed inside the check transaction"""
    prescription = create_basic_prescription()
    id_pres = prescription.id

    with _mock_presmed_dispatch() as lambda_client:
        response = client.post(
            CHECK_URL, json=_check_payload(id_pres), headers=analyst_headers
        )

    assert response.status_code == 200

    assert lambda_client.invoke.call_count == 1
    invoke_kwargs = lambda_client.invoke.call_args.kwargs
    assert invoke_kwargs["FunctionName"] == "test-backend-function"
    assert invoke_kwargs["InvocationType"] == "Event"

    payload = _dispatched_payloads(lambda_client)[0]
    assert payload["command"] == "lambda_check.mark_presmed_checked"
    assert payload["schema"] == "demo"
    assert payload["id_prescription_list"] == [str(id_pres)]

    # presmed itself must NOT be touched in-process anymore
    session.expire_all()
    drugs = (
        session.query(PrescriptionDrug)
        .filter(PrescriptionDrug.idPrescription == id_pres)
        .filter(PrescriptionDrug.suspendedDate == None)
        .all()
    )
    assert len(drugs) > 0
    for drug in drugs:
        assert drug.checked is not True


def test_check_prescription_no_dispatch_without_function_name(
    client, analyst_headers
):
    """Check prescription: when BACKEND_FUNCTION_NAME is not configured the
    presmed marking is skipped entirely and the check still succeeds"""
    prescription = create_basic_prescription()
    id_pres = prescription.id

    with _mock_presmed_dispatch(function_name="") as lambda_client:
        response = client.post(
            CHECK_URL, json=_check_payload(id_pres), headers=analyst_headers
        )

    assert response.status_code == 200
    lambda_client.invoke.assert_not_called()

    session.expire_all()
    p = session.query(Prescription).filter(Prescription.id == id_pres).first()
    assert p.status == "s"


def test_check_prescription_dispatch_failure_does_not_fail_request(
    client, analyst_headers
):
    """Check prescription: a lambda dispatch failure is logged but the check
    is already committed and the request succeeds"""
    prescription = create_basic_prescription()
    id_pres = prescription.id

    with _mock_presmed_dispatch() as lambda_client:
        lambda_client.invoke.side_effect = Exception("lambda unavailable")
        response = client.post(
            CHECK_URL, json=_check_payload(id_pres), headers=analyst_headers
        )

    assert response.status_code == 200

    session.expire_all()
    p = session.query(Prescription).filter(Prescription.id == id_pres).first()
    assert p.status == "s"


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
    """Check prescription: suspended presmed rows are excluded from
    checkedindex (the checado marking of suspended rows is handled by the
    async lambda handler, tested in backend-private)"""

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
    result = session.execute(
        text(
            "SELECT COUNT(*) FROM demo.checkedindex WHERE fkprescricao = :id AND fkmedicamento = 44"
        ),
        {"id": id_pres},
    )
    assert result.scalar() == 0

    result = session.execute(
        text("SELECT COUNT(*) FROM demo.checkedindex WHERE fkprescricao = :id"),
        {"id": id_pres},
    )
    assert result.scalar() == 1


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


def test_uncheck_does_not_dispatch_presmed_event(client, analyst_headers):
    """Uncheck prescription: the presmed checado event is only dispatched on
    check, never on uncheck (checado is preserved on uncheck)"""

    prescription = create_basic_prescription()
    id_pres = prescription.id

    with _mock_presmed_dispatch() as lambda_client:
        # Check first — dispatches the event
        client.post(
            CHECK_URL, json=_check_payload(id_pres, status="s"), headers=analyst_headers
        )
        assert lambda_client.invoke.call_count == 1

        # Then uncheck — must not dispatch again
        response = client.post(
            CHECK_URL, json=_check_payload(id_pres, status="0"), headers=analyst_headers
        )

    assert response.status_code == 200
    assert lambda_client.invoke.call_count == 1

    session.expire_all()
    p = session.query(Prescription).filter(Prescription.id == id_pres).first()
    assert p.status == "0"


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
    with _mock_presmed_dispatch() as lambda_client:
        client.post(
            CHECK_URL,
            json={"status": "s", "idPrescription": id},
            headers=analyst_headers,
        )

    # the presmed event carries only the internal prescription that was
    # checked — never the agg record nor prescriptions outside the agg
    payloads = _dispatched_payloads(lambda_client)
    assert len(payloads) == 1
    assert payloads[0]["id_prescription_list"] == [str(prescriptionid1)]

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


def test_check_internal_prescription_agg_ignores_material_only(
    client, analyst_headers
):
    """Check internal prescription: agg status becomes 's' even when an unchecked
    Materiais-only prescription remains inside the aggregation"""

    admission = test_counters["admission_number"]
    id_agg = test_counters["id_prescription"]
    id_normal = id_agg + 1
    id_material = id_agg + 2

    test_counters["id_prescription"] += 3
    test_counters["admission_number"] += 1

    date = datetime.now()

    # aggregate prescription
    create_prescription(
        id=id_agg, admissionNumber=admission, idPatient=1, agg=True, date=date
    )

    # internal prescription with a normal drug
    create_prescription(
        id=id_normal, admissionNumber=admission, idPatient=1, date=date
    )
    create_prescription_drug(
        id=int(f"{id_normal}001"), idPrescription=id_normal, idDrug=3
    )

    # internal prescription containing only "Materiais" items
    create_prescription(
        id=id_material, admissionNumber=admission, idPatient=1, date=date
    )
    create_prescription_drug(
        id=int(f"{id_material}001"),
        idPrescription=id_material,
        idDrug=4,
    )
    # Set origem via raw SQL — the ORM insert does not reliably persist it (because of the trigger)
    session.execute(
        text("UPDATE demo.presmed SET origem = :source WHERE fkpresmed = :id"),
        {"source": DrugTypeEnum.MATERIAL.value, "id": int(f"{id_material}001")},
    )
    session_commit()

    response = client.post(
        CHECK_URL, json=_check_payload(id_normal), headers=analyst_headers
    )
    assert response.status_code == 200

    session.expire_all()

    # Materiais-only prescription remains unchecked but no longer blocks the agg
    agg = session.query(Prescription).filter(Prescription.id == id_agg).first()
    assert agg.status == "s"

    material = (
        session.query(Prescription).filter(Prescription.id == id_material).first()
    )
    assert material.status == "0"


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


def test_for_update_blocks_until_lock_released(analyst_headers):
    """with_for_update() blocks a check request while the prescription row is externally locked.
    Once the external lock is released the request proceeds and succeeds (200).
    """
    prescription = create_basic_prescription()
    id_pres = prescription.id

    # Acquire a row-level lock from the test session — transaction stays open, no commit yet
    session.query(Prescription).filter(Prescription.id == id_pres).with_for_update().first()

    result = {"status_code": None, "done": False}

    def do_check():
        # Each thread gets its own Flask request context and its own DB session
        with flask_app.test_client() as tc:
            response = tc.post(
                CHECK_URL, json=_check_payload(id_pres), headers=analyst_headers
            )
            result["status_code"] = response.status_code
            result["done"] = True

    t = threading.Thread(target=do_check)
    t.start()

    # Give the thread enough time to reach the SELECT FOR UPDATE and block at PostgreSQL
    time.sleep(0.2)
    assert not result["done"], "Request should be waiting for the row lock"

    # Release the lock — the blocked request can now acquire it and proceed
    session_commit()

    t.join(timeout=5)

    assert result["done"]
    assert result["status_code"] == 200
    session.expire_all()
    p = session.query(Prescription).filter(Prescription.id == id_pres).first()
    assert p.status == "s"
