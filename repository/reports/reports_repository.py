"""Repository for managing reports."""

from sqlalchemy import and_, text

from models.appendix import Report
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


def get_saved_queries(schema: str) -> list[dict]:
    """List saved queries."""

    query = """
        select
            title,
            sql_report
        from
            public.vanna_report
        where
            schema_report = :schema
        order by
            idreport desc
    """

    query_result = db.session.execute(text(query), {"schema": schema}).all()
    results = []
    for i in query_result:
        results.append({"title": i.title, "sql_report": i.sql_report})

    return results
