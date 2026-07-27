"""Repository: simple lists"""

from sqlalchemy import or_

from models.appendix import ICDTable
from models.main import db


def list_icds() -> list[ICDTable]:
    """List icds"""
    return (
        db.session.query(ICDTable)
        .filter(ICDTable.status == 1)
        .order_by(ICDTable.name)
        .all()
    )


def find_icds(term: str, limit: int = 50) -> list[ICDTable]:
    """Search icds by code (nu_cid10) or description (no_cid10)"""
    like = f"%{term}%"
    return (
        db.session.query(ICDTable)
        .filter(ICDTable.status == 1)
        .filter(or_(ICDTable.name.ilike(like), ICDTable.id_str.ilike(like)))
        .order_by(ICDTable.name)
        .limit(limit)
        .all()
    )


def find_icds_by_ids(ids: list) -> list[ICDTable]:
    """Resolve icds by their codes (nu_cid10)"""
    if not ids:
        return []

    return (
        db.session.query(ICDTable)
        .filter(ICDTable.id_str.in_([str(i) for i in ids]))
        .order_by(ICDTable.name)
        .all()
    )
