from utils import status
from sqlalchemy import asc

from models.main import db
from models.appendix import *
from services import permission_service

from exception.validation_error import ValidationError


def get_frequencies(has_daily_frequency=None):
    q = db.session.query(Frequency)

    if has_daily_frequency != None:
        if has_daily_frequency:
            q = q.filter(Frequency.dailyFrequency != None)
        else:
            q = q.filter(Frequency.dailyFrequency == None)

    return q.order_by(asc(Frequency.description)).all()


def update_frequency(id, daily_frequency, fasting, user):
    if not permission_service.has_maintainer_permission(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    freq = Frequency.query.get(id)
    if freq is None:
        raise ValidationError(
            "Registro inexistente", "errors.invalidRecord", status.HTTP_401_UNAUTHORIZED
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
                "fasting": p.fasting,
            }
        )

    return list
