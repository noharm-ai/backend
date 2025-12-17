"""Repository for managing reports."""

from sqlalchemy import text

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
            title
    """

    query_result = db.session.execute(text(query), {"schema": schema}).all()
    results = []
    for i in query_result:
        results.append({"title": i.title, "sql_report": i.sql_report})

    return results
