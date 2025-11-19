"""Repository: tag related operations"""

from models.main import db
from models.appendix import ClinicalNotesType


def list_clinical_notes_types(active: bool) -> list[ClinicalNotesType]:
    """List clinical notes types"""
    query = db.session.query(ClinicalNotesType)

    query = query.filter(ClinicalNotesType.active == active)

    return query.order_by(ClinicalNotesType.name).all()
