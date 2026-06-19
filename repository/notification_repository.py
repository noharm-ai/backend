"""Repository for notification queries."""

from datetime import date

from sqlalchemy import asc, func, not_, or_

from models.appendix import Memory
from models.main import Notify, db


def get_active_notifications(schema: str, user_id: int) -> list[dict]:
    """Return up to 10 active, non-dismissed notifications visible to the given schema."""
    dismissed_subq = (
        db.session.query(Memory.kind)
        .filter(
            Memory.kind
            == func.concat(
                "info-alert-", func.cast(Notify.id, db.String), f"-{user_id}"
            )
        )
        .correlate(Notify)
        .exists()
    )

    results = (
        db.session.query(Notify)
        .filter(Notify.startDate <= date.today())
        .filter(Notify.endDate >= date.today())
        .filter(or_(Notify.schema == schema, Notify.schema == None))
        .filter(not_(dismissed_subq))
        .order_by(asc(Notify.id))
        .limit(10)
        .all()
    )

    return [
        {
            "id": n.id,
            "title": n.title,
            "tooltip": n.tooltip,
            "link": n.link,
            "icon": n.icon,
            "classname": n.classname,
            "text": n.text,
            "target_group": n.target_group,
            "date": n.startDate.isoformat() if n.startDate else None,
        }
        for n in results
    ]
