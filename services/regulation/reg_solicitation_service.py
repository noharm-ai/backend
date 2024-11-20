from decorators.has_permission_decorator import has_permission, Permission
from repository.regulation import reg_solicitation_repository
from models.regulation import RegSolicitation, RegSolicitationType
from models.prescription import Patient
from utils import dateutils, status
from exception.validation_error import ValidationError


@has_permission(Permission.READ_REGULATION)
def get_solicitation(id: int):
    solicitation_object = reg_solicitation_repository.get_solicitation(id=id)

    if not solicitation_object:
        raise ValidationError(
            "Registro inválido",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    solicitation: RegSolicitation = solicitation_object.RegSolicitation
    solicitation_type: RegSolicitationType = solicitation_object.RegSolicitationType
    patient: Patient = solicitation_object.Patient

    return {
        "id": str(solicitation.id),
        "stage": solicitation.stage,
        "date": dateutils.to_iso(solicitation.date),
        "type": solicitation_type.name if solicitation_type else None,
        "risk": solicitation.risk,
        "attendant": solicitation.attendant,
        "attendantRecord": solicitation.attendant_record,
        "cid": solicitation.cid,
        "justification": solicitation.justification,
        "patient": {
            "id": str(solicitation.id_patient),
            "birthdate": dateutils.to_iso(patient.birthdate) if patient else None,
            "gender": patient.gender if patient else None,
        },
    }
