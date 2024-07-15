from sqlalchemy import asc, func

from models.main import db
from models.prescription import SegmentDepartment, Department


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
