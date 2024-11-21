from datetime import datetime

from decorators.has_permission_decorator import has_permission, Permission
from repository.regulation import reg_solicitation_repository
from models.main import db, User
from models.regulation import RegSolicitation, RegSolicitationType, RegMovement
from models.prescription import Patient
from models.requests.regulation_movement_request import RegulationMovementRequest
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
    movements = _get_movements(solicitation=solicitation)

    return {
        "id": str(solicitation.id),
        "stage": solicitation.stage,
        "date": dateutils.to_iso(solicitation.date),
        "type": solicitation_type.name if solicitation_type else None,
        "idRegSolicitationType": solicitation.id_reg_solicitation_type,
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
        "movements": movements,
    }


def _get_movements(solicitation: RegSolicitation):
    movements = []
    records = reg_solicitation_repository.get_solicitation_movement(
        id_reg_solicitation=solicitation.id
    )

    for i in records:
        reg_movement: RegMovement = i.RegMovement
        responsible: User = i.User

        movements.append(
            {
                "id": str(reg_movement.id),
                "origin": reg_movement.stage_origin,
                "destination": reg_movement.stage_destination,
                "action": reg_movement.action,
                "data": reg_movement.data,
                "createdAt": dateutils.to_iso(reg_movement.created_at),
                "createdBy": responsible.name if responsible else None,
            }
        )

    # initial event
    movements.append(
        {
            "id": "0",
            "origin": None,
            "destination": None,
            "action": -1,
            "data": None,
            "createdAt": dateutils.to_iso(solicitation.date),
            "createdBy": None,
        }
    )

    return movements


@has_permission(Permission.WRITE_REGULATION)
def move(request_data: RegulationMovementRequest, user_context: User):
    solicitation: RegSolicitation = (
        db.session.query(RegSolicitation)
        .filter(RegSolicitation.id == request_data.id)
        .first()
    )

    if not solicitation:
        raise ValidationError(
            "Registro inválido",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    movement = RegMovement()
    movement.id_reg_solicitation = solicitation.id
    movement.stage_origin = solicitation.stage
    movement.stage_destination = request_data.nextStage
    movement.action = request_data.action
    movement.data = request_data.actionData
    movement.created_at = datetime.today()
    movement.created_by = user_context.id

    db.session.add(movement)

    # update solicitation data
    solicitation.stage = request_data.nextStage
    db.session.flush()

    return _get_movements(solicitation=solicitation)
