from flask_api import status
from sqlalchemy import asc, func

from models.main import db
from models.appendix import *
from models.prescription import *

from exception.validation_error import ValidationError

def get_reasons(id = None):
    parent = db.aliased(InterventionReason)
    query_editable = db.session.\
        query(func.count(Intervention.id))\
        .select_from(Intervention)\
        .filter(Intervention.idInterventionReason.any(InterventionReason.id))

    q = db.session\
        .query(\
            InterventionReason,\
            parent.description.label('parent_name'),\
            func.concat(func.coalesce(parent.description, ''), InterventionReason.description).label('concat_field'),\
            query_editable.exists().label('protected')
        )\
        .outerjoin(parent, InterventionReason.mamy == parent.id)\
        .order_by(asc('concat_field'))
    
    if id != None:
        q = q.filter(InterventionReason.id == id)

    return q.all()

def upsert_reason(id, reason: InterventionReason , user):
    roles = user.config['roles'] if user.config and 'roles' in user.config else []
    if ('admin' not in roles):
        raise ValidationError('Usuário não autorizado', 'errors.unauthorizedUser', status.HTTP_401_UNAUTHORIZED)
    
    is_protected = False
    
    if id != None:
        records = get_reasons(id)
        if (len(records) == 0):
            raise ValidationError('Registro inexistente', 'errors.invalidRecord', status.HTTP_400_BAD_REQUEST)
        
        record = records[0][0]
        is_protected = records[0][3]
    else:
        record = InterventionReason()

    if not is_protected:
        record.description = reason.description
        record.mamy = reason.mamy

    record.idHospital = reason.idHospital
    record.active = reason.active
    record.suspension = reason.suspension
    record.substitution = reason.substitution
    record.relation_type = reason.relation_type

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
            'active': r[0].active,
            'suspension': r[0].suspension,
            'substitution': r[0].substitution,
            'relationType': r[0].relation_type,
            'protected': r[3]
        })

    return list

