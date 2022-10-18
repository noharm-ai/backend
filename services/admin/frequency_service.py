from flask_api import status
from sqlalchemy import asc

from models.main import db
from models.appendix import *

from exception.validation_error import ValidationError

def get_frequencies():
    return db.session\
        .query(Frequency)\
        .order_by(asc(Frequency.description))\
        .all()

def update_daily_frequency(id, daily_frequency, user):
    roles = user.config['roles'] if user.config and 'roles' in user.config else []
    if ('suporte' not in roles):
        raise ValidationError('Usuário não autorizado', 'errors.unauthorizedUser', status.HTTP_401_UNAUTHORIZED)

    freq = Frequency.query.get(id)
    if (freq is None):
        raise ValidationError('Registro inexistente', 'errors.invalidRecord', status.HTTP_401_UNAUTHORIZED)

    freq.dailyFrequency = daily_frequency

    db.session.add(freq)
    db.session.flush()

    return freq

def list_to_dto(frequencies):
    list = []
    
    for p in frequencies:
        list.append({
            'id': p.id,
            'name': p.description,
            'dailyFrequency': p.dailyFrequency
        })

    return list

