from flask import Blueprint
from flask_api import status
from models.main import *
from models.prescription import *
from .prescription import getPrescription
from .utils import tryCommit, strNone
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

    result, stat = getPrescription(idPrescription)

    drugList = result['data']['prescription']
    drugList.extend(result['data']['solution'])
    drugList.extend(result['data']['procedures'])

    alerts = pScore = score1 = score2 = score3 = 0
    am = av = control = np = tube = diff = 0
    for d in drugList: 
        if d['whiteList'] or d['suspended']: continue

        alerts += len(d['alerts'])
        pScore += int(d['score'])
        score1 += int(d['score'] == '1')
        score2 += int(d['score'] == '2')
        score3 += int(int(d['score']) > 2)
        am += int(d['am']) if not d['am'] is None else 0
        av += int(d['av']) if not d['av'] is None else 0
        np += int(d['np']) if not d['np'] is None else 0
        control += int(d['c']) if not d['c'] is None else 0
        diff += int(not d['checked'])
        tubes = ['sonda', 'sg', 'se']
        tube += int(any(t in strNone(d['route']).lower() for t in tubes))

    interventions = 0
    for i in result['data']['interventions']:
        interventions += int(i['status'] == 's')

    exams = result['data']['alertExams']

    p.features = {
        'alerts': alerts,
        'prescriptionScore': pScore,
        'scoreOne': score1,
        'scoreTwo': score2,
        'scoreThree': score3,
        'am': am,
        'av': av,
        'controlled': control,
        'np': np,
        'tube': tube,
        'diff': diff,
        'alertExams': exams,
        'interventions': interventions,
    }
    
    return tryCommit(db, idPrescription)