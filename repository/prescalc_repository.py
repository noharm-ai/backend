"""Repository for prescalc operations"""

from datetime import datetime

from sqlalchemy import and_, any_, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import aliased

from models.enums import PrescriptionAuditTypeEnum, PrescriptionDrugAuditTypeEnum
from models.main import db
from models.prescription import (
    PrescriptionAudit,
    PrescriptionDrug,
    PrescriptionDrugAudit,
)


PRESCALC_LOCK_TIMEOUT_SECONDS = 15


def acquire_admission_lock(
    schema: str, admission_number: int, timeout_seconds: float = None
) -> bool:
    """
    Serializes prescalc per schema+admission using a transaction-scoped advisory lock.

    Concurrent prescalc executions for the same admission compute the same
    agg prescription id and race on its insert/update. The lock is released
    automatically at commit/rollback.

    Waits up to timeout_seconds (default PRESCALC_LOCK_TIMEOUT_SECONDS) for the
    lock. Returns True if acquired; False on timeout — in that case the aborted
    transaction is rolled back and the caller should skip processing.
    """
    timeout = (
        timeout_seconds if timeout_seconds is not None else PRESCALC_LOCK_TIMEOUT_SECONDS
    )

    try:
        # SET does not accept bind params; int() sanitizes. Value in ms.
        db.session.execute(text(f"SET LOCAL lock_timeout = '{int(timeout * 1000)}'"))
        db.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"prescalc:{schema}:{admission_number}"},
        )
        # restore the session value so the timeout doesn't leak into later
        # row-lock waits in the same transaction
        db.session.execute(text("SET LOCAL lock_timeout = DEFAULT"))
        return True
    except OperationalError as e:
        if getattr(e.orig, "pgcode", None) == "55P03":  # lock_not_available
            # lock_timeout aborts the transaction; clear it before returning
            db.session.rollback()
            return False
        raise


def get_processed_status(id_prescription_list: list[int]):
    """
    Get the processed status of prescriptions.

    Args:
        id_prescription_list (list[int]): List of prescription IDs.

    Returns:
        str: The processed status of the prescriptions.
    """
    query = (
        select(
            PrescriptionDrug.id, func.count(PrescriptionDrugAudit.id).label("p_count")
        )
        .select_from(PrescriptionDrug)
        .outerjoin(
            PrescriptionDrugAudit,
            and_(
                PrescriptionDrug.id == PrescriptionDrugAudit.idPrescriptionDrug,
                PrescriptionDrugAudit.auditType
                == PrescriptionDrugAuditTypeEnum.PROCESSED.value,
            ),
        )
        .where(PrescriptionDrug.idPrescription == any_(id_prescription_list))
        .group_by(PrescriptionDrug.id)
    )

    results = db.session.execute(query).all()

    not_processed_count = 0
    for r in results:
        if r.p_count == 0:
            not_processed_count += 1

    if not_processed_count == len(results):
        return "NEW_PRESCRIPTION"

    if not_processed_count > 0:
        return "NEW_ITENS"

    return "PROCESSED"


def get_processed_outpatient_status(
    id_prescription_list: list[int], agg_date: datetime
):
    """
    Check if patient has new itens at agg_date. Useful for outpatient cpoe.

    PROCESSED no new itens at agg_date or all new itens at agg_date are processed
    PENDING new itens not processed
    """
    PrescriptionDrugAuditProcessed = aliased(PrescriptionDrugAudit)

    query = (
        select(
            PrescriptionDrug.id,
            func.count(PrescriptionDrugAuditProcessed.id).label("p_count"),
        )
        .select_from(PrescriptionDrug)
        .join(
            PrescriptionDrugAudit,
            and_(
                PrescriptionDrug.id == PrescriptionDrugAudit.idPrescriptionDrug,
                PrescriptionDrugAudit.auditType
                == PrescriptionDrugAuditTypeEnum.UPSERT.value,
                func.date(PrescriptionDrugAudit.createdAt) == func.date(agg_date),
            ),
        )
        .outerjoin(
            PrescriptionDrugAuditProcessed,
            and_(
                PrescriptionDrug.id
                == PrescriptionDrugAuditProcessed.idPrescriptionDrug,
                PrescriptionDrugAuditProcessed.auditType
                == PrescriptionDrugAuditTypeEnum.PROCESSED.value,
            ),
        )
        .where(PrescriptionDrug.idPrescription == any_(id_prescription_list))
        .group_by(PrescriptionDrug.id)
    )

    results = db.session.execute(query).all()

    not_processed_count = 0
    for r in results:
        if r.p_count == 0:
            not_processed_count += 1

    if not_processed_count > 0:
        return "PENDING"

    return "PROCESSED"


def get_last_check_data(id_prescription: int):
    """Get data from last prescription check"""
    query = (
        select(PrescriptionAudit)
        .where(PrescriptionAudit.idPrescription == id_prescription)
        .where(PrescriptionAudit.auditType == PrescriptionAuditTypeEnum.CHECK.value)
        .order_by(PrescriptionAudit.createdAt.desc())
        .limit(1)
    )

    return db.session.execute(query).first()
