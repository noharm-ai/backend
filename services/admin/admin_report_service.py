"""Service for admin reports."""

import json
from datetime import datetime

from flask_sqlalchemy.session import Session

from decorators.has_permission_decorator import Permission, has_permission
from exception.authorization_error import AuthorizationError
from exception.validation_error import ValidationError
from models.main import User, db
from models.requests.admin.admin_report_request import (
    CopySourceGraphsRequest,
    CopySourceListRequest,
    UpdateReportGraphsRequest,
)
from repository.reports import reports_repository
from services import auth_service
from utils import logger, status


@has_permission(Permission.WRITE_CUSTOM_REPORTS_GRAPHS)
def update_report_graphs(
    id_report: int, request_data: UpdateReportGraphsRequest, user_context: User
):
    """Update only the graphs field of a report."""
    report = reports_repository.get_report(id_report=id_report)

    if not report:
        raise ValidationError(
            "Relatório não encontrado",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    report.graphs = request_data.graphs
    report.updated_at = datetime.now()
    report.updated_by = user_context.id

    db.session.flush()

    return {"id": report.id, "graphs": report.graphs}


@has_permission(Permission.WRITE_CUSTOM_REPORTS_GRAPHS)
def get_copy_source_reports(request_data: CopySourceListRequest, user_context: User):
    """List the custom reports whose charts may be copied into another report."""
    source_schema = _authorize_source_schema(
        user_context=user_context, source_schema=request_data.sourceSchema
    )

    db_session = _open_schema_session(schema=source_schema)
    try:
        reports = reports_repository.get_active_custom_reports_from_session(
            db_session=db_session
        )

        return [
            {
                "id": report.id,
                "name": report.name,
                "description": report.description,
                "status": report.status,
                "processedAt": (
                    report.processed_at.isoformat() if report.processed_at else None
                ),
                "graphCount": len(_normalize_graphs(report.graphs)),
            }
            for report in reports
        ]
    finally:
        db_session.close()


@has_permission(Permission.WRITE_CUSTOM_REPORTS_GRAPHS)
def get_copy_source_graphs(request_data: CopySourceGraphsRequest, user_context: User):
    """Get the chart configurations of a copy-source report."""
    source_schema = _authorize_source_schema(
        user_context=user_context, source_schema=request_data.sourceSchema
    )

    db_session = _open_schema_session(schema=source_schema)
    try:
        report = reports_repository.get_report_from_session(
            db_session=db_session, id_report=request_data.idReport
        )

        if not report or not report.active:
            raise ValidationError(
                "Relatório de origem não encontrado",
                "errors.invalidRecord",
                status.HTTP_400_BAD_REQUEST,
            )

        return {
            "id": report.id,
            "name": report.name,
            "sourceSchema": source_schema,
            "graphs": _normalize_graphs(report.graphs),
        }
    finally:
        db_session.close()


def _authorize_source_schema(user_context: User, source_schema: str) -> str:
    """Resolve and authorize the schema the charts are copied from."""
    if not source_schema or source_schema == user_context.schema:
        return user_context.schema

    if not auth_service.can_read_foreign_schema_as_maintainer(
        user=user_context, target_schema=source_schema
    ):
        raise AuthorizationError()

    logger.backend_logger.info(
        "cross-schema report chart read: user=%s from=%s to=%s",
        user_context.id,
        source_schema,
        user_context.schema,
    )

    return source_schema


def _open_schema_session(schema: str) -> Session:
    """Open a session bound to `schema`, isolated from the request session.

    A rollback on the request session clears its schema_translate_map, so the
    foreign read gets its own session instead of re-pointing the current one.
    """
    db_session = Session(db)
    db_session.connection(execution_options={"schema_translate_map": {None: schema}})

    return db_session


def _normalize_graphs(raw) -> list:
    """Return the stored charts as a list.

    The chart editor writes a JSON string into the JSON column, while rows
    written elsewhere hold a real array, so both shapes reach this point.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []

    return raw if isinstance(raw, list) else []
