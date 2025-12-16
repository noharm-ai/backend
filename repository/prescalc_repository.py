"""Repository for prescalc operations"""

from datetime import datetime

from sqlalchemy import and_, any_, func, select
from sqlalchemy.orm import aliased

from models.enums import PrescriptionAuditTypeEnum, PrescriptionDrugAuditTypeEnum
from models.main import db
from models.prescription import (
    PrescriptionAudit,
    PrescriptionDrug,
    PrescriptionDrugAudit,
)


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
