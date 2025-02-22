"""Repository: prescription history report related operations"""

from sqlalchemy import func, select

from models.main import db, User
from models.prescription import (
    PrescriptionAudit,
    PrescriptionDrugAudit,
    PrescriptionDrug,
)
from models.enums import PrescriptionDrugAuditTypeEnum


def get_audit_report(id_prescription: int):
    """Get data from prescricao_audit table ordered by createdAt asc"""
    return (
        db.session.query(PrescriptionAudit, User)
        .outerjoin(User, PrescriptionAudit.createdBy == User.id)
        .filter(PrescriptionAudit.idPrescription == id_prescription)
        .order_by(PrescriptionAudit.createdAt.asc())
        .all()
    )


def get_prescription_audit_dates(id_prescription: int):
    """Get the arrival and prescalc dates of a prescription"""
    dates = {"arrival_date": None, "process_date": None}
    prescription_query = select(PrescriptionDrug.id).where(
        PrescriptionDrug.idPrescription == id_prescription
    )

    query = (
        select(func.min(PrescriptionDrugAudit.createdAt).label("arrival_date"))
        .select_from(PrescriptionDrugAudit)
        .where(PrescriptionDrugAudit.idPrescriptionDrug.in_(prescription_query))
        .where(
            PrescriptionDrugAudit.auditType
            == PrescriptionDrugAuditTypeEnum.UPSERT.value
        )
    )

    result = db.session.execute(query).first()

    if result:
        dates["arrival_date"] = result.arrival_date

    query = (
        select(func.min(PrescriptionDrugAudit.createdAt).label("process_date"))
        .select_from(PrescriptionDrugAudit)
        .where(PrescriptionDrugAudit.idPrescriptionDrug.in_(prescription_query))
        .where(
            PrescriptionDrugAudit.auditType
            == PrescriptionDrugAuditTypeEnum.PROCESSED.value
        )
    )

    result = db.session.execute(query).first()

    if result:
        dates["process_date"] = result.process_date

    return dates
