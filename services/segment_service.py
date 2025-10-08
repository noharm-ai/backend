"""Service: segment related operations"""

from sqlalchemy import asc, and_

from models.main import db
from models.segment import Segment
from models.appendix import SegmentDepartment, Department
from models.enums import FeatureEnum
from services import feature_service
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


def is_cpoe(id_segment: int):
    """Check if segment is cpoe or not"""

    if not id_segment:
        return False

    segment = db.session.query(Segment).filter(Segment.id == id_segment).first()

    if not segment:
        return False

    return segment.cpoe


def get_ignored_segments(is_cpoe_flag: bool):
    """When the system is in CPOE mode, we can  ignore non-CPOE segments when the feature IGNORE_NON_CPOE_SEGMENTS is enabled"""
    if not is_cpoe_flag:
        return None

    # ignore non cpoe segments when the feature is enabled
    ignore_non_cpoe_segments = feature_service.has_feature(
        FeatureEnum.IGNORE_NON_CPOE_SEGMENTS
    )

    if ignore_non_cpoe_segments:
        # ignore non cpoe segments
        ignore_segments = []
        segments = get_segments()
        for s in segments:
            if not s.cpoe:
                ignore_segments.append(s.id)

        return ignore_segments

    return None
