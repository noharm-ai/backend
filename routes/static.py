from flask import Blueprint, request
from flask_api import status
from models.main import *
from models.prescription import *
from .prescription import getPrescription
from .utils import tryCommit, strNone, getFeatures
from datetime import date
from random import random 

app_stc = Blueprint('app_stc',__name__)

@app_stc.route('/static/<string:schema>/prescription/<int:idPrescription>', methods=['GET'])
def computePrescription(schema, idPrescription):
    result = db.engine.execute('SELECT schema_name FROM information_schema.schemata')

    schemaExists = False
    for r in result:
        if r[0] == schema: schemaExists = True

    if not schemaExists:
        return { 'status': 'error', 'message': 'Schema Inexistente!' }, status.HTTP_400_BAD_REQUEST

    dbSession.setSchema(schema)
    p = Prescription.query.get(idPrescription)
    if (p is None):
        return { 'status': 'error', 'message': 'Prescrição Inexistente!' }, status.HTTP_400_BAD_REQUEST

    if (p.idSegment is None):
        return { 
            'status': 'success', 
            'data': idPrescription,
            'message': 'Prescrição sem Segmento!' 
        }, status.HTTP_200_OK

    resultPresc, stat = getPrescription(idPrescription=idPrescription)
    p.features = getFeatures(resultPresc)
    p.aggDrugs = p.features['drugIDs']
    p.aggDeps = [p.idDepartment]
    
    newPrescAgg = False
    PrescAggID = genAggID(p)
    pAgg = Prescription.query.get(PrescAggID)
    if (pAgg is None):
        pAgg = Prescription()
        pAgg.id = PrescAggID
        pAgg.idPatient = p.idPatient
        pAgg.admissionNumber = p.admissionNumber
        pAgg.date = date(p.date.year, p.date.month, p.date.day)
        newPrescAgg = True

    resultAgg, stat = getPrescription(admissionNumber=p.admissionNumber, aggDate=pAgg.date)

    pAgg.idHospital = p.idHospital
    pAgg.idDepartment = p.idDepartment
    pAgg.idSegment = p.idSegment
    pAgg.bed = p.bed
    pAgg.record = p.record
    pAgg.prescriber = 'Prescrição Agregada'
    pAgg.agg = True
    pAgg.status = 0
    pAgg.features = getFeatures(resultAgg)
    pAgg.aggDrugs = pAgg.features['drugIDs']
    pAgg.aggDeps = list(set([resultAgg['data']['headers'][h]['idDepartment'] for h in resultAgg['data']['headers']]))

    if newPrescAgg: db.session.add(pAgg)

    return tryCommit(db, idPrescription)

def genAggID(p):
    id = (p.date.year - 2000) * 100000000000000
    id += p.date.month *          1000000000000
    id += p.date.day *              10000000000
    id += p.admissionNumber
    return id

@app_stc.route('/prescriptions/static/<int:idPrescription>', methods=['GET'])
def getPrescriptionNoAuth(idPrescription):
    dbSession.setSchema('demo')

    p = Prescription.getPrescription(idPrescription)

    if (p is None):
        return { 'status': 'error', 'message': 'Prescrição Inexistente!' }, status.HTTP_400_BAD_REQUEST
    else:
        return getPrescription(idPrescription=idPrescription)

@app_stc.route('/prescriptions/static/<int:idPrescription>', methods=['POST'])
def addPrescriptionNoAuth(idPrescription):
    data = request.get_json()
    dbSession.setSchema('demo')

    p = Prescription.query.get(idPrescription)

    if (p is None):
        p = Prescription()
        p.id = idPrescription
        p.idDepartment = data.get('idDept')
        p.idPatient = data.get('idPatient')
        p.date = datetime.today()

        db.session.add(p)

    return tryCommit(db, p.id)