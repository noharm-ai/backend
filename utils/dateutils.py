from datetime import datetime


def to_iso(date: datetime):
    if date != None:
        if isinstance(date, str):
            return date

        return date.isoformat()

    return None
