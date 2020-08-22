import copy
from flask_api import status
from models.main import *
from models.appendix import *
from models.segment import *
from models.prescription import *
from flask import Blueprint, request
from flask_jwt_extended import (create_access_token, create_refresh_token,
                                jwt_required, jwt_refresh_token_required, get_jwt_identity, get_raw_jwt)
from .utils import *
from datetime import  datetime

app_pat = Blueprint('app_pat',__name__)

def historyExam(typeExam, examsList, segExam):
    results = []
    for e in examsList:
        if e.typeExam == typeExam:
            item = formatExam(e, e.typeExam.lower(), segExam)
            del(item['ref'])
            results.append(item)
    return results

@app_pat.route("/exams/<int:admissionNumber>", methods=['GET'])
@jwt_required
def getExamsbyAdmission(admissionNumber):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    idSegment = request.args.get('idSegment', 1)
    examsList = Exams.findByAdmission(admissionNumber)
    segExam = SegmentExam.refDict(idSegment)

    perc = {
        'h_conleuc': {
            'total' : 1,
            'relation': ['h_conlinfoc', 'h_conmono', 'h_coneos', 'h_conbaso', 'h_consegm']
        }
    }

    bufferList = {}
    typeExams = []
    for e in examsList:
        if not e.typeExam in typeExams and e.typeExam.lower() in segExam:
            key = e.typeExam.lower()
            item = formatExam(e, e.typeExam.lower(), segExam)
            item['name'] = segExam[e.typeExam.lower()].name
            item['perc'] = None
            item['history'] = historyExam(e.typeExam, examsList, segExam)
            bufferList[key] = item
            typeExams.append(e.typeExam)
            if key in perc:
                perc[key]['total'] = float(e.value)

    for p in perc:
        total = perc[p]['total']
        for r in perc[p]['relation']:
            if r in bufferList:
                val = bufferList[r]['value']
                bufferList[r]['perc'] = round((val*100)/total,1)

    results = copy.deepcopy(segExam)
    for e in segExam:
        if e in bufferList:
            results[e] = bufferList[e]
        else:
            del(results[e])

    return {
        'status': 'success',
        'data': results
    }, status.HTTP_200_OK


@app_pat.route('/patient/<int:admissionNumber>', methods=['POST'])
@jwt_required
def setPatientData(admissionNumber):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    data = request.get_json()

    p = Patient.findByAdmission(admissionNumber)
    if (p is None):
        return { 'status': 'error', 'message': 'Paciente Inexistente!' }, status.HTTP_400_BAD_REQUEST

    updateWeight = False
    weight = data.get('weight', None)
    if weight and weight != p.weight: 
        p.weightDate = datetime.today()
        p.weight = weight
        p.user = user.id
        updateWeight = True

    alertExpire = data.get('alertExpire', None)
    if alertExpire and alertExpire != p.alertExpire: 
        p.alert = data.get('alert', None)
        p.alertExpire = alertExpire
        p.alertDate = datetime.today()
        p.alertBy = user.id

    if 'height' in data.keys(): p.height = data.get('height', None)
    if 'observation' in data.keys(): p.observation = data.get('observation', None)

    p.update = datetime.today()

    if 'idPrescription' in data.keys() and updateWeight:
        idPrescription = data.get('idPrescription')

        query = "INSERT INTO " + user.schema + ".presmed \
                    SELECT *\
                    FROM " + user.schema + ".presmed\
                    WHERE fkprescricao = " + str(int(idPrescription)) + ";"

        db.engine.execute(query) 

    return tryCommit(db, admissionNumber, User.permission(user))