"""Repository for managing reports."""

from models.appendix import Report
from models.main import db


def get_custom_reports(all: bool = False):
    """Get all custom reports."""

    query = db.session.query(Report)

    if not all:
        query = query.filter(Report.active)

    return query.order_by(Report.name).all()


def get_report(id_report: int):
    """Get single report by ID."""
    return db.session.query(Report).filter(Report.id == id_report).first()
