from flask_api import status
from math import ceil

from models.main import *
from models.appendix import *
from models.segment import *
from models.enums import RoleEnum
from services.admin import drug_service, integration_service

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


def get_outliers_process_list(id_segment, user):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if RoleEnum.ADMIN.value not in roles and RoleEnum.TRAINING.value not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    print("Init Schema:", user.schema, "Segment:", id_segment)
    fold_size = 25

    query = f"""
        INSERT INTO {user.schema}.outlier 
        (idsegmento, fkmedicamento, doseconv, frequenciadia, contagem)
        SELECT 
            idsegmento, fkmedicamento, ROUND(doseconv::numeric,2) as doseconv, frequenciadia, SUM(contagem)
        FROM
            {user.schema}.prescricaoagg
        WHERE 
            idsegmento = :idSegment
            and frequenciadia is not null and doseconv is not null
        GROUP BY 
            idsegmento, fkmedicamento, ROUND(doseconv::numeric,2), frequenciadia
        ON CONFLICT DO nothing
    """

    result = db.session.execute(query, {"idSegment": id_segment})
    print("RowCount", result.rowcount)

    # fix inconsistencies after outlier insert
    drug_service.fix_inconsistency(user)

    totalCount = (
        db.session.query(func.count(distinct(Outlier.idDrug)))
        .select_from(Outlier)
        .filter(Outlier.idSegment == id_segment)
        .scalar()
    )
    folds = ceil(totalCount / fold_size)
    print("Total Count:", totalCount, folds)

    processesUrl = []

    if integration_service.can_refresh_agg(user.schema):
        processesUrl.append(
            {"url": "/admin/integration/refresh-agg", "method": "POST", "params": {}}
        )

    for fold in range(1, folds + 1):
        processesUrl.append(
            {
                "url": f"/segments/{str(int(id_segment))}/outliers/generate/fold/{str(fold)}",
                "method": "GET",
                "params": {},
            }
        )

    return processesUrl
