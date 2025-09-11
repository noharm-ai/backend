"""Service: segment related operations"""

from sqlalchemy import asc, and_

from models.main import db
from models.segment import Segment
from models.appendix import SegmentDepartment, Department
from decorators.has_permission_decorator import has_permission, Permission


@has_permission(Permission.READ_BASIC_FEATURES)
def get_segments():
    """list all segments"""
    return db.session.query(Segment).order_by(asc(Segment.description)).all()


@has_permission(Permission.READ_BASIC_FEATURES)
def get_segment_departments():
    """List segment departments"""

    results = (
        db.session.query(
            SegmentDepartment.idDepartment,
            SegmentDepartment.id,
            Department.name,
        )
        .join(
            Department,
            and_(
                Department.id == SegmentDepartment.idDepartment,
                Department.idHospital == SegmentDepartment.idHospital,
            ),
        )
        .group_by(SegmentDepartment.idDepartment, SegmentDepartment.id, Department.name)
        .order_by(asc(Department.name))
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


@has_permission(Permission.READ_BASIC_FEATURES)
def is_cpoe(id_segment: int):
    """Check if segment is cpoe or not"""

    if not id_segment:
        return False

    segment = db.session.query(Segment).filter(Segment.id == id_segment).first()

    if not segment:
        return False

    return segment.cpoe
