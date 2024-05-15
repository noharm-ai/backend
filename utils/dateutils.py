from datetime import datetime


def toIso(date: datetime):
    if date != None:
        return date.isoformat()

    return None
