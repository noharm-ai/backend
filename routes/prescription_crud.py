import os
from flask_api import status
from models.main import *
from models.appendix import *
from models.segment import *
from models.prescription import *
from flask import Blueprint, request
from flask_jwt_extended import (jwt_required, get_jwt_identity)
from .utils import *
from datetime import datetime

app_pres_crud = Blueprint('app_pres_crud',__name__)

@app_pres_crud.route('/editPrescription/drug/<int:idPrescriptionDrug>', methods=['PUT'])
@jwt_required()
def updatePrescriptionDrug(idPrescriptionDrug):
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ['TZ'] = 'America/Sao_Paulo'

    roles = user.config['roles'] if user.config and 'roles' in user.config else []
    if ('prescriptionEdit' not in roles):
        return {
            'status': 'error',
            'message': 'Usuário não autorizado',
            'code': 'errors.unauthorizedUser'
        }, status.HTTP_401_UNAUTHORIZED

    pdUpdate = PrescriptionDrug.query.get(idPrescriptionDrug)
    if (pdUpdate is None):
        return { 'status': 'error', 'message': 'Registro Inexistente!', 'code': 'errors.invalidRegister' }, status.HTTP_400_BAD_REQUEST

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

    pd = PrescriptionDrug.findByPrescriptionDrugComplete(idPrescriptionDrug)
    pdWhiteList = bool(pd[6].whiteList) if pd[6] is not None else False

    result = {
      'idPrescription': str(pd[0].idPrescription),
      'idPrescriptionDrug': str(pd[0].id),
      'idDrug': pd[0].idDrug,
      'drug': pd[1].name if pd[1] is not None else 'Medicamento ' + str(pd[0].idDrug),
      'dose': pd[0].dose,
      'measureUnit': { 'value': pd[2].id, 'label': pd[2].description } if pd[2] else '',
      'frequency': { 'value': pd[3].id, 'label': pd[3].description } if pd[3] else '',
      'dayFrequency': pd[0].frequency,
      'doseconv': pd[0].doseconv,
      'time': timeValue(data.get('interval', None)),
      'interval': pd[0].interval,
      'route': pd[0].route,
      'score': str(pd[5]) if not pdWhiteList and pd[0].source != 'Dietas' else '0',
    }

    return tryCommit(db, result, user.permission())

@app_pres_crud.route('/editPrescription/drug', methods=['POST'])
@jwt_required()
def createPrescriptionDrug():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ['TZ'] = 'America/Sao_Paulo'

    roles = user.config['roles'] if user.config and 'roles' in user.config else []
    if ('prescriptionEdit' not in roles):
        return {
            'status': 'error',
            'message': 'Usuário não autorizado',
            'code': 'errors.unauthorizedUser'
        }, status.HTTP_401_UNAUTHORIZED

    pdCreate = PrescriptionDrug()

    pdCreate.id = PrescriptionDrug.getNextId(data.get('idPrescription', None), user.schema)
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

    pd = PrescriptionDrug.findByPrescriptionDrugComplete(pdCreate.id)
    pdWhiteList = bool(pd[6].whiteList) if pd[6] is not None else False

    result = {
      'idPrescription': str(pd[0].idPrescription),
      'idPrescriptionDrug': str(pd[0].id),
      'idDrug': pd[0].idDrug,
      'drug': pd[1].name if pd[1] is not None else 'Medicamento ' + str(pd[0].idDrug),
      'dose': pd[0].dose,
      'measureUnit': { 'value': pd[2].id, 'label': pd[2].description } if pd[2] else '',
      'frequency': { 'value': pd[3].id, 'label': pd[3].description } if pd[3] else '',
      'dayFrequency': pd[0].frequency,
      'doseconv': pd[0].doseconv,
      'time': timeValue(data.get('interval', None)),
      'interval': pd[0].interval,
      'route': pd[0].route,
      'score': str(pd[5]) if not pdWhiteList and pd[0].source != 'Dietas' else '0',
      'np': pd[6].notdefault if pd[6] is not None else False,
      'am': pd[6].antimicro if pd[6] is not None else False,
      'av': pd[6].mav if pd[6] is not None else False,
      'c': pd[6].controlled if pd[6] is not None else False,
      'q': pd[6].chemo if pd[6] is not None else False,
      'alergy': bool(pd[0].allergy == 'S'),
      'allergy': bool(pd[0].allergy == 'S'),
      'whiteList': pdWhiteList,
    }

    return tryCommit(db, result, user.permission())

@app_pres_crud.route('/editPrescription/drug/<int:idPrescriptionDrug>/suspend/<int:suspend>', methods=['PUT'])
@jwt_required()
def suspend(idPrescriptionDrug, suspend):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ['TZ'] = 'America/Sao_Paulo'

    roles = user.config['roles'] if user.config and 'roles' in user.config else []
    if ('prescriptionEdit' not in roles):
        return {
            'status': 'error',
            'message': 'Usuário não autorizado',
            'code': 'errors.unauthorizedUser'
        }, status.HTTP_401_UNAUTHORIZED

    pdUpdate = PrescriptionDrug.query.get(idPrescriptionDrug)
    if (pdUpdate is None):
        return { 'status': 'error', 'message': 'Registro Inexistente!', 'code': 'errors.invalidRegister' }, status.HTTP_400_BAD_REQUEST

    if (suspend == 1):
      pdUpdate.suspendedDate = datetime.today()
    else:
      pdUpdate.suspendedDate = None

    pdUpdate.update = datetime.today()
    pdUpdate.user = user.id
      
    db.session.add(pdUpdate)
    db.session.flush()

    result = {
      'idPrescription': str(pdUpdate.idPrescription),
      'idPrescriptionDrug': str(pdUpdate.id),
      'idDrug': pdUpdate.idDrug,
      'suspended': True if suspend == 1 else False
    }

    return tryCommit(db, result, user.permission())