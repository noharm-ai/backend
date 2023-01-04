import random
from flask_api import status
from models.main import *
from models.appendix import *
from models.prescription import *
from flask import Blueprint, request
from flask_jwt_extended import (create_access_token, create_refresh_token,
                                jwt_required, get_jwt_identity)
from datetime import date, datetime
from .utils import tryCommit

app_itrv = Blueprint('app_itrv',__name__)

@app_itrv.route('/prescriptions/drug/<int:idPrescriptionDrug>/<int:drugStatus>', methods=['PUT'])
@jwt_required()
def setDrugStatus(idPrescriptionDrug, drugStatus):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    pd = PrescriptionDrug.query.get(idPrescriptionDrug)
    if pd is not None:
        pd.status = drugStatus
        pd.update = datetime.today()
        pd.user = user.id

    return tryCommit(db, str(idPrescriptionDrug), user.permission())

@app_itrv.route('/intervention/<int:idPrescriptionDrug>', methods=['PUT'])
@jwt_required()
def createIntervention(idPrescriptionDrug):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    data = request.get_json()

    if idPrescriptionDrug == 0: 
        idPrescription = data.get('idPrescription', 0)
    else:
        idPrescription = 0

    newIntervention = False
    i = Intervention.query.get((idPrescriptionDrug, idPrescription))
    if i is None:
        i = Intervention()
        i.id = idPrescriptionDrug
        i.idPrescription = idPrescription
        i.date = datetime.today()
        i.update = datetime.today()
        i.user = user.id
        newIntervention = True

    if 'admissionNumber' in data.keys(): i.admissionNumber = data.get('admissionNumber', None)
    if 'idInterventionReason' in data.keys(): i.idInterventionReason = data.get('idInterventionReason', None)
    if 'error' in data.keys(): i.error = data.get('error', None)
    if 'cost' in data.keys(): i.cost = data.get('cost', None)
    if 'observation' in data.keys(): i.notes = data.get('observation', None)
    if 'interactions' in data.keys(): i.interactions = data.get('interactions', None)
    if 'transcription' in data.keys(): i.transcription = data.get('transcription', None)
    
    i.status = data.get('status', 's')

    if newIntervention: db.session.add(i)

    setDrugStatus(idPrescriptionDrug, i.status)

    return tryCommit(db, str(idPrescriptionDrug), user.permission())

def sortReasons(e):
  return e['description']

@app_itrv.route("/intervention/reasons", methods=['GET'])
@jwt_required()
def getInterventionReasons():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    
    results = InterventionReason.findAll()

    iList = []
    for i in results:
        iList.append({
            'id': i[0].id,
            'description': i[1] + ' - ' +  i[0].description if i[1] else i[0].description
        })

    iList.sort(key=sortReasons)

    return {
        'status': 'success',
        'data': iList
    }, status.HTTP_200_OK

@app_itrv.route("/intervention", methods=['GET'])
@jwt_required()
def getInterventions():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    
    results = Intervention.findAll(userId=user.id)

    return {
        'status': 'success',
        'data': results
    }, status.HTTP_200_OK