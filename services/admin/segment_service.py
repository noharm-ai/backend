from utils import status

from models.main import *
from models.appendix import *
from models.segment import *
from models.enums import RoleEnum, IntegrationStatusEnum
from services.admin import integration_status_service

from exception.validation_error import ValidationError


def upsert_segment(id_segment, description, active, user):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if RoleEnum.ADMIN.value not in roles and RoleEnum.TRAINING.value not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    if id_segment:
        segment = db.session.query(Segment).filter(Segment.id == id_segment).first()
        if segment == None:
            raise ValidationError(
                "Registro inválido",
                "errors.invalidRecord",
                status.HTTP_400_BAD_REQUEST,
            )
    else:
        if (
            integration_status_service.get_integration_status(user.schema)
            == IntegrationStatusEnum.PRODUCTION.value
        ):
            raise ValidationError(
                "O processo de criação de segmentos foi desativado para integrações em Produção. Solicite criação manual.",
                "errors.businessRules",
                status.HTTP_400_BAD_REQUEST,
            )

        segment = Segment()

    segment.description = description
    segment.status = 1 if active else 0

    db.session.add(segment)


def get_departments(id_segment):
    sd = db.aliased(SegmentDepartment)
    q_department = (
        db.session.query(func.count(sd.id).label("count"))
        .select_from(sd)
        .filter(sd.idHospital == Department.idHospital)
        .filter(sd.idDepartment == Department.id)
        .filter(sd.id != id_segment)
    )

    departments = (
        db.session.query(
            Department,
            Hospital,
            SegmentDepartment,
            q_department.as_scalar().label("total"),
        )
        .join(Hospital, Department.idHospital == Hospital.id)
        .outerjoin(
            SegmentDepartment,
            and_(
                SegmentDepartment.idDepartment == Department.id,
                SegmentDepartment.idHospital == Department.idHospital,
                SegmentDepartment.id == id_segment,
            ),
        )
        .order_by(asc(Department.name))
        .all()
    )

    deps = []
    for d in departments:
        deps.append(
            {
                "idHospital": d[0].idHospital,
                "hospitalName": d[1].name,
                "idDepartment": d[0].id,
                "name": d[0].name,
                "checked": d[2] is not None,
                "uses": d[3],
            }
        )

    return deps


def update_segment_departments(id_segment, department_list, user):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if RoleEnum.ADMIN.value not in roles and RoleEnum.TRAINING.value not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    if id_segment == None:
        raise ValidationError(
            "Parâmetro inválido", "errors.invalidParam", status.HTTP_400_BAD_REQUEST
        )

    db.session.query(SegmentDepartment).filter(
        SegmentDepartment.id == id_segment
    ).delete()

    for d in department_list:
        if d["idHospital"] == None or d["idDepartment"] == None:
            raise ValidationError(
                "Parâmetro inválido", "errors.invalidParam", status.HTTP_400_BAD_REQUEST
            )

        sd = SegmentDepartment()
        sd.id = id_segment
        sd.idHospital = d["idHospital"]
        sd.idDepartment = d["idDepartment"]

        db.session.add(sd)
