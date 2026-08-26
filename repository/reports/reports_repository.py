"""Repository for managing reports."""

from sqlalchemy import and_

from models.appendix import Report
from models.enums import ReportTypeEnum
from models.main import User, db


def get_custom_reports(schema: str, all: bool = False):
    """Get all custom reports and the user who last processed each one.

    Returns (Report, processed_by_name) rows. The name is resolved only when the
    processing user belongs to `schema`: reports processed by users from other
    schemas are still listed, but with the name as None.
    """

    query = db.session.query(Report, User.name.label("processed_by_name")).outerjoin(
        User, and_(User.id == Report.processed_by, User.schema == schema)
    )

    if not all:
        query = query.filter(Report.active)

    return query.order_by(Report.name).all()


def get_report(id_report: int):
    """Get single report by ID."""
    return db.session.query(Report).filter(Report.id == id_report).first()


def get_active_custom_reports_from_session(db_session):
    """List the active custom reports visible through an explicitly scoped session.

    The schema comes from the session's schema_translate_map, so a caller reading
    another schema never builds a schema name into the query.
    """
    return (
        db_session.query(Report)
        .filter(Report.active)
        .filter(Report.report_type == ReportTypeEnum.CUSTOM.value)
        .order_by(Report.name)
        .all()
    )


def get_report_from_session(db_session, id_report: int):
    """Get a single report by ID through an explicitly scoped session."""
    return db_session.query(Report).filter(Report.id == id_report).first()
