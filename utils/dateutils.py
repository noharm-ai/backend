from datetime import datetime


def to_iso(date: datetime):
    if date != None:
        return date.isoformat()

    return None
