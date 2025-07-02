"""Repository: simple lists"""

from models.main import db
from models.appendix import ICDTable
from models.requests.tag_request import TagListRequest


def list_icds() -> list[ICDTable]:
    """List icds"""
    return (
        db.session.query(ICDTable)
        .filter(ICDTable.status == 1)
        .order_by(ICDTable.name)
        .all()
    )
