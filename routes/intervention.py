import random
from flask_api import status
from models import db, User, PrescriptionDrug, InterventionReason, Intervention, setSchema, PrescriptionPic
from flask import Blueprint, request
from flask_jwt_extended import (create_access_token, create_refresh_token,
                                jwt_required, jwt_refresh_token_required, get_jwt_identity, get_raw_jwt)
from datetime import date, datetime
from .prescription import getPrescriptions
from .utils import tryCommit

app_itrv = Blueprint('app_itrv',__name__)

@app_itrv.route('/prescriptions/drug/<int:idPrescriptionDrug>/<int:drugStatus>', methods=['PUT'])
@jwt_required
def setDrugStatus(idPrescriptionDrug, drugStatus):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    pd = PrescriptionDrug.query.get(idPrescriptionDrug)
    pd.status = drugStatus
    pd.update = datetime.today()
    pd.user = user.id

    ppic = PrescriptionPic.query.get(pd.idPrescription)
    if ppic is None:
        pObj, code = getPrescriptions(idPrescription=pd.idPrescription)
        ppic = PrescriptionPic()
        ppic.id = pd.idPrescription
        ppic.picture = pObj['data'][0]
        db.session.add(ppic)

    return tryCommit(db, idPrescriptionDrug)

@app_itrv.route('/intervention/<int:idPrescriptionDrug>', methods=['PUT'])
@jwt_required
def createIntervention(idPrescriptionDrug=None):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)
    data = request.get_json()

    newIntervention = False
    i = Intervention.query.get(idPrescriptionDrug)
    if i is None:
        i = Intervention()
        i.id = idPrescriptionDrug
        i.date = datetime.today()
        newIntervention = True
        i.update = datetime.today()
        i.user = user.id

    if 'admissionNumber' in data.keys(): i.admissionNumber = data.get('admissionNumber', None)
    if 'idInterventionReason' in data.keys(): i.idInterventionReason = data.get('idInterventionReason', None)
    if 'error' in data.keys(): i.error = data.get('error', None)
    if 'cost' in data.keys(): i.cost = data.get('cost', None)
    if 'observation' in data.keys(): i.notes = data.get('observation', None)
    if 'interactions' in data.keys(): i.interactions = data.get('interactions', None)
    
    i.status = data.get('status', 's')

    if newIntervention: db.session.add(i)

    setDrugStatus(idPrescriptionDrug, i.status)

    return tryCommit(db, idPrescriptionDrug)

def sortReasons(e):
  return e['description']

@app_itrv.route("/intervention/reasons", methods=['GET'])
@jwt_required
def getInterventionReasons():
    user = User.find(get_jwt_identity())
    setSchema(user.schema)
    
    results = InterventionReason.findAll()
    db.engine.dispose()

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
@jwt_required
def getInterventions():
    user = User.find(get_jwt_identity())
    setSchema(user.schema)
    
    results = Intervention.findAll(userId=user.id)
    db.engine.dispose()

    return {
        'status': 'success',
        'data': results
    }, status.HTTP_200_OK