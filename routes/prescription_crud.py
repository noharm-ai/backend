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
from services.prescription_drug_service import getPrescriptionDrug, prescriptionDrugToDTO
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

    pd = getPrescriptionDrug(idPrescriptionDrug)

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

    pd = getPrescriptionDrug(newId)

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