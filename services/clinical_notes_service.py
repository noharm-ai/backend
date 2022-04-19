from models.main import db

from models.appendix import *
from models.notes import ClinicalNotes
from models.prescription import *
from services import memory_service

from exception.validation_error import ValidationError

def create_clinical_notes(data, user):
    if not memory_service.has_feature('PRIMARYCARE'):
        raise ValidationError(\
            'Usuário não autorizado', 'errors.unauthorizedUser', status.HTTP_401_UNAUTHORIZED\
        )

    user_complete = db.session.query(User).get(user.id)
    cn = ClinicalNotes()
    
    cn.id = get_next_id(user.schema)
    cn.admissionNumber = data.get('admissionNumber', None)
    cn.date = data.get('date', datetime.today())
    cn.text = data.get('text', None)
    cn.prescriber = user_complete.name
    cn.update = datetime.today()
    cn.user = user.id
    cn.position = 'Farmacêutica'

    db.session.add(cn)
    db.session.flush()

    return cn.id

def get_next_id(schema):
    result = db.session.execute("SELECT NEXTVAL('" + schema + ".evolucao_fkevolucao_seq')")

    return ([row[0] for row in result])[0]