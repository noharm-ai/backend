from models.main import db, User
from models.prescription import PrescriptionAudit


def get_audit_report(id_prescription: int):
    return (
        db.session.query(PrescriptionAudit, User)
        .outerjoin(User, PrescriptionAudit.createdBy == User.id)
        .filter(PrescriptionAudit.idPrescription == id_prescription)
        .order_by(PrescriptionAudit.createdAt.asc())
        .all()
    )
