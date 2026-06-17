"""Repository for notification queries."""

from datetime import date

from sqlalchemy import asc, or_

from models.main import Notify, db


def get_active_notifications(
    schema: str, exclude_ids: list[int] | None = None
) -> list[dict]:
    """Return up to 10 active notifications visible to the given schema, excluding dismissed IDs."""
    query = (
        db.session.query(Notify)
        .filter(Notify.startDate <= date.today())
        .filter(Notify.endDate >= date.today())
        .filter(or_(Notify.schema == schema, Notify.schema == None))
        .order_by(asc(Notify.id))
    )
    if exclude_ids:
        query = query.filter(Notify.id.notin_(exclude_ids))
    results = query.limit(10).all()
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
