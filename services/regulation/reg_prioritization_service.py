from decorators.has_permission_decorator import has_permission, Permission
from repository.regulation import reg_solicitation_repository
from models.regulation import RegSolicitation, RegSolicitationType
from models.prescription import Patient


@has_permission(Permission.READ_REGULATION)
def get_prioritization():
    results = reg_solicitation_repository.get_prioritization()
    records = []

    for item in results:
        solicitation: RegSolicitation = item.RegSolicitation
        solicitation_type: RegSolicitationType = item.RegSolicitationType
        patient: Patient = item.Patient

        records.append(
            {
                "id": str(solicitation.id),
                "date": solicitation.date.isoformat(),
                "idPatient": str(solicitation.id_patient),
                "risk": solicitation.risk,
                "type": solicitation_type.name if solicitation_type else None,
                "birthdate": patient.birthdate if patient else None,
            }
        )

    return records
