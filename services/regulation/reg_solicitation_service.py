from datetime import datetime

from decorators.has_permission_decorator import has_permission, Permission
from repository.regulation import reg_solicitation_repository
from models.main import db, User
from models.regulation import RegSolicitation, RegSolicitationType, RegMovement
from models.prescription import Patient
from models.requests.regulation_movement_request import RegulationMovementRequest
from models.requests.regulation_solicitation_request import (
    RegulationSolicitationRequest,
)
from models.enums import RegulationAction
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
        "admissionNumber": solicitation.admission_number,
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
        "extra": {
            "scheduleDate": dateutils.to_iso(solicitation.schedule_date),
            "transportationDate": dateutils.to_iso(solicitation.transportation_date),
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
                "template": reg_movement.template,
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
    solicitation_ids = []
    if request_data.id:
        solicitation_ids.append(request_data.id)
    else:
        solicitation_ids = request_data.ids

    if not solicitation_ids:
        raise ValidationError(
            "Nenhuma solicitção selecionada",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    results = []
    for id in solicitation_ids:
        solicitation: RegSolicitation = (
            db.session.query(RegSolicitation).filter(RegSolicitation.id == id).first()
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
        movement.template = request_data.actionDataTemplate
        movement.created_at = datetime.today()
        movement.created_by = user_context.id

        db.session.add(movement)

        # update solicitation data
        solicitation.stage = request_data.nextStage

        if "scheduleDate" in movement.data:
            solicitation.schedule_date = datetime.strptime(
                movement.data.get("scheduleDate"), "%d/%m/%Y %H:%M"
            )

        if "transportationDate" in movement.data:
            solicitation.transportation_date = datetime.strptime(
                movement.data.get("transportationDate"), "%d/%m/%Y %H:%M"
            )

        update_reg_type = False
        if "reg_type" in movement.data and movement.data.get("reg_type", None) != None:
            update_reg_type = True
            solicitation.id_reg_solicitation_type = movement.data.get(
                "reg_type", {}
            ).get("value")

        if "reg_risk" in movement.data:
            solicitation.risk = movement.data.get("reg_risk")

        # undo actions
        if movement.action == RegulationAction.UNDO_SCHEDULE.value:
            solicitation.schedule_date = None

        if movement.action == RegulationAction.UNDO_TRANSPORTATION_SCHEDULE.value:
            solicitation.transportation_date = None

        db.session.flush()

        results.append(
            {
                "id": str(solicitation.id),
                "stage": solicitation.stage,
                "risk": solicitation.risk,
                "extra": {
                    "scheduleDate": dateutils.to_iso(solicitation.schedule_date),
                    "transportationDate": dateutils.to_iso(
                        solicitation.transportation_date
                    ),
                    "regType": {
                        "type": (
                            movement.data.get("reg_type", {}).get("label")
                            if update_reg_type
                            else None
                        ),
                        "idRegSolicitationType": (
                            movement.data.get("reg_type", {}).get("value")
                            if update_reg_type
                            else None
                        ),
                    },
                },
                "movements": (
                    _get_movements(solicitation=solicitation)
                    if len(solicitation_ids) == 1
                    else []
                ),
            }
        )

    return results


@has_permission(Permission.WRITE_REGULATION)
def create(request_data: RegulationSolicitationRequest, user_context: User):
    """Creates new solicitations"""
    # add patient
    patient = Patient()
    patient.idHospital = 1
    patient.idPatient = request_data.idPatient
    patient.birthdate = request_data.birthdate
    patient.admissionNumber = reg_solicitation_repository.get_next_admission_number()
    patient.admissionDate = datetime.today()
    patient.update = datetime.today()
    patient.user = user_context.id
    db.session.add(patient)
    db.session.flush()

    # add reg solicitation
    solicitation = RegSolicitation()
    solicitation.id = reg_solicitation_repository.get_next_solicitation_id()
    solicitation.admission_number = patient.admissionNumber
    solicitation.id_patient = request_data.idPatient
    solicitation.date = request_data.solicitationDate
    solicitation.id_reg_solicitation_type = request_data.idRegSolicitationType
    solicitation.id_department = request_data.idDepartment
    solicitation.risk = request_data.risk
    solicitation.cid = request_data.cid
    solicitation.attendant = request_data.attendant
    solicitation.attendant_record = request_data.attendantRecord
    solicitation.justification = request_data.justification
    solicitation.stage = 0
    solicitation.created_at = datetime.today()
    solicitation.created_by = user_context.id
    db.session.add(solicitation)
    db.session.flush()

    return {"id": str(solicitation.id)}
