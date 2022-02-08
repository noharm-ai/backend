from flask_api import status
from flask_jwt_extended import (get_jwt_identity)

from models.main import db
from models.appendix import *
from models.prescription import *
from services import prescription_drug_service

from exception.validation_error import ValidationError

def get_next_id(idPrescription, schema):
    result = db.session.execute(\
      "SELECT\
        CONCAT(p.fkprescricao, LPAD(COUNT(*)::VARCHAR, 3, '0'))\
      FROM " + schema + ".presmed p\
      WHERE\
        p.fkprescricao = :id\
      GROUP BY\
        p.fkprescricao",
      {'id': idPrescription}
    )

    return ([row[0] for row in result])[0]

def create(data):
    user = User.find(get_jwt_identity())
    roles = user.config['roles'] if user.config and 'roles' in user.config else []
    if ('prescriptionEdit' not in roles):
        raise ValidationError('Usuário não autorizado', 'errors.unauthorizedUser', status.HTTP_401_UNAUTHORIZED)

    pdCreate = PrescriptionDrug()

    pdCreate.id = get_next_id(data.get('idPrescription', None), user.schema)
    pdCreate.idPrescription = data.get('idPrescription', None)
    pdCreate.source = data.get('source', None)

    pdCreate.idDrug = data.get('idDrug', None)
    pdCreate.dose = data.get('dose', None)
    pdCreate.idMeasureUnit = data.get('measureUnit', None)
    pdCreate.idFrequency = data.get('frequency', None)
    pdCreate.interval = data.get('interval', None)
    pdCreate.route = data.get('route', None)

    pdCreate.update = datetime.today()
    pdCreate.user = user.id
      
    db.session.add(pdCreate)
    db.session.flush()

    return prescription_drug_service.get(pdCreate.id)

def update(idPrescriptionDrug, data):
    user = User.find(get_jwt_identity())

    roles = user.config['roles'] if user.config and 'roles' in user.config else []
    if ('prescriptionEdit' not in roles):
        raise ValidationError('Usuário não autorizado', 'errors.unauthorizedUser', status.HTTP_401_UNAUTHORIZED)

    pdUpdate = PrescriptionDrug.query.get(idPrescriptionDrug)
    if (pdUpdate is None):
        raise ValidationError('Registro Inexistente!', 'errors.invalidRegister', status.HTTP_400_BAD_REQUEST)

    pdUpdate.update = datetime.today()
    pdUpdate.user = user.id

    if 'dose' in data.keys(): 
        pdUpdate.dose = data.get('dose', None)

    if 'measureUnit' in data.keys(): 
        pdUpdate.idMeasureUnit = data.get('measureUnit', None)

    if 'frequency' in data.keys(): 
        pdUpdate.idFrequency = data.get('frequency', None)

    if 'interval' in data.keys(): 
        pdUpdate.interval = data.get('interval', None)

    if 'route' in data.keys(): 
        pdUpdate.route = data.get('route', None)
      
    db.session.add(pdUpdate)
    db.session.flush()

    #calc score
    query = "\
      INSERT INTO " + user.schema + ".presmed \
        SELECT *\
        FROM " + user.schema + ".presmed\
        WHERE fkpresmed = :id"

    db.session.execute(query, {'id': idPrescriptionDrug})

    return prescription_drug_service.get(idPrescriptionDrug)

def toggle_suspension(idPrescriptionDrug, suspend):
    user = User.find(get_jwt_identity())
    roles = user.config['roles'] if user.config and 'roles' in user.config else []
    if ('prescriptionEdit' not in roles):
        raise ValidationError('Usuário não autorizado', 'errors.unauthorizedUser', status.HTTP_401_UNAUTHORIZED)

    pdUpdate = PrescriptionDrug.query.get(idPrescriptionDrug)
    if (pdUpdate is None):
        return { 'status': 'error', 'message': 'Registro Inexistente!', 'code': 'errors.invalidRegister' }, status.HTTP_400_BAD_REQUEST

    if (suspend == True):
        pdUpdate.suspendedDate = datetime.today()
    else:
        pdUpdate.suspendedDate = None

    pdUpdate.update = datetime.today()
    pdUpdate.user = user.id
      
    db.session.add(pdUpdate)
    db.session.flush()

    return pdUpdate