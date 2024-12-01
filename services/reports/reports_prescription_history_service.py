from decorators.has_permission_decorator import has_permission, Permission
from repository.reports import reports_prescription_history_repository
from models.main import User, db
from models.prescription import PrescriptionAudit, Prescription
from utils import dateutils, status
from exception.validation_error import ValidationError


@has_permission(Permission.READ_REPORTS)
def get_prescription_history(id_prescription: int):
    prescription: Prescription = (
        db.session.query(Prescription)
        .filter(Prescription.id == id_prescription)
        .first()
    )

    if not prescription:
        raise ValidationError(
            "Prescrição inexistente",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    results = []

    if not prescription.agg:
        # add custom events
        if prescription.origin_created_at:
            results.append(
                {
                    "id": str(prescription.id) + "1",
                    "source": "custom",
                    "type": 1,
                    "idPrescription": str(prescription.id),
                    "createdAt": dateutils.to_iso(prescription.origin_created_at),
                    "responsible": "Sistema origem",
                }
            )

        prescription_audit_dates = (
            reports_prescription_history_repository.get_prescription_audit_dates(
                id_prescription=id_prescription
            )
        )

        if prescription_audit_dates.get("arrival_date"):
            results.append(
                {
                    "id": str(prescription.id) + "2",
                    "source": "custom",
                    "type": 2,
                    "idPrescription": str(prescription.id),
                    "createdAt": dateutils.to_iso(
                        prescription_audit_dates.get("arrival_date")
                    ),
                    "responsible": None,
                }
            )

        if prescription_audit_dates.get("process_date"):
            results.append(
                {
                    "id": str(prescription.id) + "3",
                    "source": "custom",
                    "type": 3,
                    "idPrescription": str(prescription.id),
                    "createdAt": dateutils.to_iso(
                        prescription_audit_dates.get("process_date")
                    ),
                    "responsible": None,
                }
            )

    audit_records = reports_prescription_history_repository.get_audit_report(
        id_prescription=id_prescription
    )

    for i in audit_records:
        audit: PrescriptionAudit = i.PrescriptionAudit
        responsible: User = i.User

        results.append(
            {
                "id": str(audit.id),
                "source": "PrescriptionAudit",
                "type": audit.auditType,
                "idPrescription": str(audit.idPrescription),
                "createdAt": dateutils.to_iso(audit.createdAt),
                "responsible": responsible.name if responsible else None,
            }
        )

    return sorted(results, key=lambda d: d["createdAt"])
