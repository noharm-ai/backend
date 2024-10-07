from sqlalchemy import asc, func

from models.main import db
from models.prescription import Department, Segment
from models.appendix import SegmentDepartment
from decorators.has_permission_decorator import has_permission, Permission


@has_permission(Permission.READ_BASIC_FEATURES)
def get_segments():
    return db.session.query(Segment).order_by(asc(Segment.description)).all()


@has_permission(Permission.READ_BASIC_FEATURES)
def get_segment_departments():
    results = (
        db.session.query(
            SegmentDepartment.idDepartment,
            SegmentDepartment.id,
            func.max(Department.name).label("name"),
        )
        .join(
            Department,
            Department.id == SegmentDepartment.idDepartment,
        )
        .group_by(SegmentDepartment.idDepartment, SegmentDepartment.id)
        .order_by(asc("name"))
        .all()
    )

    departments = []
    for d in results:
        departments.append(
            {
                "idSegment": d.id,
                "idDepartment": d.idDepartment,
                "label": d.name,
            }
        )

    return departments
