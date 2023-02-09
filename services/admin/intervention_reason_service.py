from flask_api import status
from sqlalchemy import asc

from models.main import db
from models.appendix import *

from exception.validation_error import ValidationError

def get_reasons():
    return db.session\
        .query(InterventionReason)\
        .order_by(asc(InterventionReason.description))\
        .all()

def update_reason(id, reason: InterventionReason , user):
    roles = user.config['roles'] if user.config and 'roles' in user.config else []
    if ('suporte' not in roles):
        raise ValidationError('Usuário não autorizado', 'errors.unauthorizedUser', status.HTTP_401_UNAUTHORIZED)

    record = InterventionReason.query.get(id)
    if (record is None):
        raise ValidationError('Registro inexistente', 'errors.invalidRecord', status.HTTP_401_UNAUTHORIZED)

    record.description = reason.description
    record.mamy = reason.mamy
    record.active = reason.active

    db.session.add(record)
    db.session.flush()

    return record

def create_reason(reason: InterventionReason, user):
    roles = user.config['roles'] if user.config and 'roles' in user.config else []
    if ('suporte' not in roles):
        raise ValidationError('Usuário não autorizado', 'errors.unauthorizedUser', status.HTTP_401_UNAUTHORIZED)

    record = InterventionReason()
    record.description = reason.description
    record.mamy = reason.mamy
    record.active = reason.active

    db.session.add(record)
    db.session.flush()

    return record

def list_to_dto(reasons):
    list = []
    
    for r in reasons:
        list.append({
            'id': r.id,
            'name': r.description,
            'parent': r.mamy,
            'active': r.active
        })

    return list

