"""Repository: help text related operations"""

from datetime import datetime

from models.appendix import HelpText
from models.main import db


def get(key: str) -> HelpText | None:
    """Get a help text record by its key."""
    return db.session.query(HelpText).filter(HelpText.key == key).first()


def upsert(key: str, content: str | None, user_id: int) -> HelpText:
    """Create or update the help text record for a given key."""
    record = get(key)
    now = datetime.today()

    if record is None:
        record = HelpText(
            key=key,
            content=content,
            created_by=user_id,
            created_at=now,
            updated_by=user_id,
            updated_at=now,
        )
        db.session.add(record)
    else:
        record.content = content
        record.updated_by = user_id
        record.updated_at = now

    db.session.flush()

    return record
