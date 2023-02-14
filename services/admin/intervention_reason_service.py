from flask_api import status
from sqlalchemy import asc, func

from models.main import db
from models.appendix import *
from functools import partial

from exception.validation_error import ValidationError

def get_reasons(id = None):
    parent = db.aliased(InterventionReason)

    q = db.session\
        .query(\
            InterventionReason,\
            parent.description.label('parent_name'),\
            func.concat(func.coalesce(parent.description, ''), InterventionReason.description).label('concat_field')\
        )\
        .outerjoin(parent, InterventionReason.mamy == parent.id)\
        .order_by(asc('concat_field'))
    
    if id != None:
        q = q.filter(InterventionReason.id == id)

    return q.all()

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

    return get_reasons(record.id)

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

    return get_reasons(record.id)

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

