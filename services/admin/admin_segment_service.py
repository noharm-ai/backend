from sqlalchemy import and_, asc, func

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import Department, SegmentDepartment
from models.main import User, db
from models.segment import Hospital, Segment
from repository import drug_attributes_repository, outlier_repository
from services.admin import admin_exam_service, admin_unit_conversion_service
from utils import status


@has_permission(Permission.ADMIN_SEGMENTS)
def upsert_segment(
    id_segment,
    description,
    active,
    user_context: User,
    type: int,
    cpoe: bool,
    id_segment_origin: int,
):
    new_record = False
    if id_segment:
        segment = db.session.query(Segment).filter(Segment.id == id_segment).first()
        if segment is None:
            raise ValidationError(
                "Registro inválido",
                "errors.invalidRecord",
                status.HTTP_400_BAD_REQUEST,
            )
    else:
        new_record = True
        segment = Segment()
        segment.cpoe_outpatient_clinic = False

    segment.description = description
    segment.status = 1 if active else 0
    segment.type = type
    segment.cpoe = cpoe if cpoe is not None else False

    db.session.add(segment)
    db.session.flush()

    if not new_record:
        # skip copy
        return

    if not id_segment_origin:
        raise ValidationError(
            "Deve ser selecionado um segmento origem",
            "errors.invalidParam",
            status.HTTP_400_BAD_REQUEST,
        )

    # start copying from origin
    drug_attributes_repository.copy_segment_drug_attributes(
        id_segment_origin=id_segment_origin,
        id_segment_destiny=segment.id,
        schema=user_context.schema,
        id_user=user_context.id,
    )

    outlier_repository.copy_segment_outliers(
        id_segment_origin=id_segment_origin,
        id_segment_destiny=segment.id,
        schema=user_context.schema,
        id_user=user_context.id,
    )

    admin_unit_conversion_service.copy_unit_conversion(
        id_segment_origin=id_segment_origin,
        id_segment_destiny=segment.id,
        user_context=user_context,
    )

    admin_exam_service.copy_exams(
        id_segment_origin=id_segment_origin,
        id_segment_destiny=segment.id,
        user_context=user_context,
    )


@has_permission(Permission.ADMIN_SEGMENTS)
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


@has_permission(Permission.ADMIN_SEGMENTS)
def update_segment_departments(id_segment, department_list):
    if id_segment is None:
        raise ValidationError(
            "Parâmetro inválido", "errors.invalidParam", status.HTTP_400_BAD_REQUEST
        )

    db.session.query(SegmentDepartment).filter(
        SegmentDepartment.id == id_segment
    ).delete()

    for d in department_list:
        if d["idHospital"] is None or d["idDepartment"] is None:
            raise ValidationError(
                "Parâmetro inválido", "errors.invalidParam", status.HTTP_400_BAD_REQUEST
            )

        sd = SegmentDepartment()
        sd.id = id_segment
        sd.idHospital = d["idHospital"]
        sd.idDepartment = d["idDepartment"]

        db.session.add(sd)
