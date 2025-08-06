from datetime import datetime, date


def to_iso(date: datetime):
    if date != None:
        if isinstance(date, str):
            return date

        return date.isoformat()

    return None


def parse_date_or_today(date_text: str):
    try:
        return datetime.strptime(date_text, "%Y-%m-%d")
    except ValueError:
        return date.today()


def data2age(birthdate):
    if birthdate is None:
        return ""

    days_in_year = 365.2425
    birthdate = birthdate.split("T")[0]
    birthdate = datetime.strptime(birthdate, "%Y-%m-%d")
    age = int((datetime.today() - birthdate).days / days_in_year)
    return age


def date_overlap(start1: datetime, end1: datetime, start2: datetime, end2: datetime):
    """
    Checks if two datetime ranges overlap.

    Args:
      start1: Datetime object for the start of the first period.
      end1: Datetime object for the end of the first period.
      start2: Datetime object for the start of the second period.
      end2: Datetime object for the end of the second period.

    Returns:
      True if the ranges overlap, False otherwise.
    """
    return start1 < end2 and start2 < end1
