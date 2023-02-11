from flask_api import status
from sqlalchemy import asc

from models.main import db
from models.appendix import *

from exception.validation_error import ValidationError

def get_reasons():
    parent = db.aliased(InterventionReason)

    return db.session\
        .query(InterventionReason, parent.description.label('parent_name'))\
        .outerjoin(parent, InterventionReason.mamy == parent.id)\
        .order_by(asc(parent.description), asc(InterventionReason.description))\
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
            'id': r[0].id,
            'name': r[0].description,
            'parentId': r[0].mamy,
            'parentName': r[1],
            'active': r[0].active
        })

    return list

