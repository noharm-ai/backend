"""Repository: getname validation links and results (public.schema_config_audit)"""

from datetime import datetime

from models.appendix import SchemaConfigAudit
from models.enums import SchemaConfigAuditTypeEnum
from models.main import db

ACTION_LINK = "create_validation_link"
ACTION_RESULT = "validation_result"


def get_link(id_link: int, lock: bool = False) -> SchemaConfigAudit | None:
    """The link row with this id, or None. ``lock`` holds the row until the
    transaction ends, so two runs of the same link are saved one at a time."""
    query = db.session.query(SchemaConfigAudit).filter(
        SchemaConfigAudit.id == id_link,
        SchemaConfigAudit.auditType == SchemaConfigAuditTypeEnum.GETNAME_VALIDATION.value,
    )

    if lock:
        query = query.with_for_update()

    link = query.first()

    if link is None or (link.extra or {}).get("action") != ACTION_LINK:
        return None

    return link


def list_results(link: SchemaConfigAudit) -> list[SchemaConfigAudit]:
    """The runs saved for a link, oldest first"""
    return (
        db.session.query(SchemaConfigAudit)
        .filter(
            SchemaConfigAudit.schemaName == link.schemaName,
            SchemaConfigAudit.auditType
            == SchemaConfigAuditTypeEnum.GETNAME_VALIDATION.value,
            SchemaConfigAudit.id > link.id,
            SchemaConfigAudit.extra["action"].as_string() == ACTION_RESULT,
            SchemaConfigAudit.extra["link_id"].as_string() == str(link.id),
        )
        .order_by(SchemaConfigAudit.id)
        .all()
    )


def count_results(link: SchemaConfigAudit) -> int:
    """How many runs a link already saved"""
    return len(list_results(link))


def add_result(link: SchemaConfigAudit, extra: dict) -> SchemaConfigAudit:
    """Save one run of a link. The row belongs to who generated the link: the
    run itself is anonymous and created_by is not nullable."""
    result = SchemaConfigAudit()
    result.schemaName = link.schemaName
    result.auditType = SchemaConfigAuditTypeEnum.GETNAME_VALIDATION.value
    result.extra = dict(extra, action=ACTION_RESULT, link_id=link.id)
    result.createdAt = datetime.today()
    result.createdBy = link.createdBy

    db.session.add(result)
    db.session.flush()

    return result
