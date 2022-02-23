from models.main import db

from models.appendix import *
from models.prescription import *

from exception.validation_error import ValidationError

def copyPrescription(idPrescription, user):
    roles = user.config['roles'] if user.config and 'roles' in user.config else []
    if ('prescriptionEdit' not in roles):
        raise ValidationError('Usuário não autorizado', 'errors.unauthorizedUser', status.HTTP_401_UNAUTHORIZED)

    pd = db.session.query(Prescription)\
        .filter(Prescription.id == idPrescription)\
        .first()

    if (pd is None):
        return False

    pdCreate = Prescription(pd)

    #generate new id
    pdCreate.id = 1
    pdCreate.date = datetime.today()
    pdCreate.expire = datetime.today()
    pdCreate.status = '0'
    pdCreate.notes = None
    pdCreate.notes_at = None
    pdCreate.agg = None
    pdCreate.aggDeps = None
    pdCreate.aggDrugs = None
    pdCreate.features = None
    pdCreate.update = datetime.today()
    pdCreate.user = user
    
    db.session.add(pdCreate)
    db.session.flush()