import os

from models.main import *
from models.appendix import *
from models.segment import *
from models.prescription import *
from flask import Blueprint, request
from flask_jwt_extended import (jwt_required, get_jwt_identity)
from .utils import *

from services.prescription_edit_service import copyPrescription
from services.prescription_drug_edit_service import createPrescriptionDrug, updatePrescriptionDrug, togglePrescriptionDrugSuspension
from exception.validation_error import ValidationError

app_pres_crud = Blueprint('app_pres_crud',__name__)

@app_pres_crud.route('/editPrescription/drug/<int:idPrescriptionDrug>', methods=['PUT'])
@jwt_required()
def actionUpdatePrescriptionDrug(idPrescriptionDrug):
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ['TZ'] = 'America/Sao_Paulo'

    try:
        updatePrescriptionDrug(idPrescriptionDrug, data, user)
    except ValidationError as e:
        return {
            'status': 'error',
            'message': e.message,
            'code': e.code
        }, e.httpStatus

    pd = PrescriptionDrug.findByPrescriptionDrugComplete(idPrescriptionDrug)

    return tryCommit(db, prescriptionDrugToDTO(pd), user.permission())

@app_pres_crud.route('/editPrescription/drug', methods=['POST'])
@jwt_required()
def actionCreatePrescriptionDrug():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ['TZ'] = 'America/Sao_Paulo'

    try:
        newId = createPrescriptionDrug(data, user)
    except ValidationError as e:
        return {
            'status': 'error',
            'message': e.message,
            'code': e.code
        }, e.httpStatus

    pd = PrescriptionDrug.findByPrescriptionDrugComplete(newId)

    return tryCommit(db, prescriptionDrugToDTO(pd), user.permission())

@app_pres_crud.route('/editPrescription/drug/<int:idPrescriptionDrug>/suspend/<int:suspend>', methods=['PUT'])
@jwt_required()
def actionSuspendPrescriptionDrug(idPrescriptionDrug, suspend):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ['TZ'] = 'America/Sao_Paulo'

    try:
        pdUpdate = togglePrescriptionDrugSuspension(idPrescriptionDrug, user, True if suspend == 1 else False)
    except ValidationError as e:
        return {
            'status': 'error',
            'message': e.message,
            'code': e.code
        }, e.httpStatus

    result = {
        'idPrescription': str(pdUpdate.idPrescription),
        'idPrescriptionDrug': str(pdUpdate.id),
        'idDrug': pdUpdate.idDrug,
        'suspended': True if suspend == 1 else False
    }

    return tryCommit(db, result, user.permission())

@app_pres_crud.route('/editPrescription/<int:idPrescription>/copy', methods=['POST'])
@jwt_required()
def actionCopyPrescription(idPrescription):
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ['TZ'] = 'America/Sao_Paulo'

    #copyPrescription(idPrescription, user)

    return tryCommit(db, 1, user.permission())

def prescriptionDrugToDTO(pd):
    pdWhiteList = bool(pd[6].whiteList) if pd[6] is not None else False

    return {
        'idPrescription': str(pd[0].idPrescription),
        'idPrescriptionDrug': str(pd[0].id),
        'idDrug': pd[0].idDrug,
        'drug': pd[1].name if pd[1] is not None else 'Medicamento ' + str(pd[0].idDrug),
        'dose': pd[0].dose,
        'measureUnit': { 'value': pd[2].id, 'label': pd[2].description } if pd[2] else '',
        'frequency': { 'value': pd[3].id, 'label': pd[3].description } if pd[3] else '',
        'dayFrequency': pd[0].frequency,
        'doseconv': pd[0].doseconv,
        'time': timeValue(pd[0].interval),
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