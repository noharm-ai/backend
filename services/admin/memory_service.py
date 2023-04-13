from flask_api import status
from sqlalchemy import or_

from models.main import db
from models.appendix import *
from models.prescription import *

from exception.validation_error import ValidationError

def get_admin_memory_itens(user):
    roles = user.config['roles'] if user.config and 'roles' in user.config else []
    if ('admin' not in roles):
        raise ValidationError('Usuário não autorizado', 'errors.unauthorizedUser', status.HTTP_401_UNAUTHORIZED)
    
    memory_itens = db.session.query(Memory)\
            .filter(Memory.kind.in_(['features', 'reports', 'getnameurl']))\
            .all()
    
    itens = []
    for i in memory_itens:
        itens.append({
            'key': i.key,
            'kind': i.kind,
            'value': i.value
        })

    return itens

def update_memory(key, kind, value , user):
    roles = user.config['roles'] if user.config and 'roles' in user.config else []
    if ('admin' not in roles):
        raise ValidationError('Usuário não autorizado', 'errors.unauthorizedUser', status.HTTP_401_UNAUTHORIZED)
    
    memory_item = db.session.query(Memory)\
            .filter(Memory.key == key)\
            .filter(Memory.kind == kind)\
            .first()
    
    if (memory_item == None):
        raise ValidationError('Registro inexistente', 'errors.invalidRecord', status.HTTP_400_BAD_REQUEST)
    
    #bkp
    memory_bkp = Memory()
    memory_bkp.kind = memory_item.kind + '_bkp'
    memory_bkp.value = memory_item.value
    memory_bkp.update = memory_item.update
    memory_bkp.user = memory_item.user
    db.session.add(memory_bkp)

    #update
    memory_item.value = value
    memory_item.update = datetime.today()
    memory_item.user = user.id

    db.session.add(memory_item)
    db.session.flush()

    return key


