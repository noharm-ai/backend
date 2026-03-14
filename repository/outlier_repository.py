"""Repository: outlier related operations"""

from models.appendix import Notes
from models.main import Outlier, db


def list_drug_outliers(id_drug: int, id_segment: int) -> list[Outlier]:
    """List drug outliers"""
    return (
        db.session.query(Outlier, Notes)
        .outerjoin(Notes, Notes.idOutlier == Outlier.id)
        .filter(Outlier.idSegment == id_segment, Outlier.idDrug == id_drug)
        .order_by(Outlier.countNum.desc(), Outlier.frequency.asc())
        .all()
    )
