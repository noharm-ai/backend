"""Repository for notification queries."""

from datetime import date

from sqlalchemy import asc, or_

from models.main import Notify, db


def get_active_notifications(schema: str) -> list[dict]:
    """Return up to 5 active notifications visible to the given schema."""
    results = (
        db.session.query(Notify)
        .filter(Notify.startDate <= date.today())
        .filter(Notify.endDate >= date.today())
        .filter(or_(Notify.schema == schema, Notify.schema == None))
        .order_by(asc(Notify.id))
        .limit(5)
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
