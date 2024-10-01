from utils import status
from sqlalchemy import asc

from models.main import db
from models.appendix import Frequency
from decorators.has_permission_decorator import has_permission, Permission
from exception.validation_error import ValidationError


@has_permission(Permission.ADMIN_FREQUENCIES)
def get_frequencies(has_daily_frequency=None):
    q = db.session.query(Frequency)

    if has_daily_frequency != None:
        if has_daily_frequency:
            q = q.filter(Frequency.dailyFrequency != None)
        else:
            q = q.filter(Frequency.dailyFrequency == None)

    return q.order_by(asc(Frequency.description)).all()


@has_permission(Permission.ADMIN_FREQUENCIES)
def update_frequency(id, daily_frequency, fasting):
    freq = Frequency.query.get(id)
    if freq is None:
        raise ValidationError(
            "Registro inexistente", "errors.invalidRecord", status.HTTP_400_BAD_REQUEST
        )

    freq.dailyFrequency = float(daily_frequency)
    freq.fasting = fasting

    db.session.add(freq)
    db.session.flush()

    return freq


def list_to_dto(frequencies):
    list = []

    for p in frequencies:
        list.append(
            {
                "id": p.id,
                "name": p.description,
                "dailyFrequency": p.dailyFrequency,
                "fasting": True if p.fasting else False,
            }
        )

    return list
