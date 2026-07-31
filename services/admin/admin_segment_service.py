from sqlalchemy import and_, asc, func

from decorators.has_permission_decorator import Permission, has_permission
from models.appendix import Department, SegmentDepartment
from models.main import db
from models.segment import Hospital


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
