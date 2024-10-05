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
