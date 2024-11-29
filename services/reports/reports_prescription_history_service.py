from decorators.has_permission_decorator import has_permission, Permission
from repository.reports import reports_prescription_history_repository
from models.main import User
from models.prescription import PrescriptionAudit
from utils import dateutils


@has_permission(Permission.READ_REPORTS)
def get_prescription_history(id_prescription: int):
    audit_records = reports_prescription_history_repository.get_audit_report(
        id_prescription=id_prescription
    )
    results = []

    for i in audit_records:
        audit: PrescriptionAudit = i.PrescriptionAudit
        responsible: User = i.User

        results.append(
            {
                "id": str(audit.id),
                "type": audit.auditType,
                "idPrescription": str(audit.idPrescription),
                "createdAt": dateutils.to_iso(audit.createdAt),
                "responsible": responsible.name if responsible else None,
            }
        )

    return results
