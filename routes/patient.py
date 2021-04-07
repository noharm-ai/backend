import os, copy
from flask_api import status
from models.main import *
from models.appendix import *
from models.segment import *
from models.prescription import *
from models.notes import ClinicalNotes
from flask import Blueprint, request
from flask_jwt_extended import (create_access_token, create_refresh_token,
                                jwt_required, get_jwt_identity)
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

def historyCalc(typeExam, examsList, patient):
    results = []
    for e in examsList:
        item = {}
        if typeExam == 'mdrd':
            item = mdrd_calc(e['value'], patient.birthdate, patient.gender, patient.skinColor)
        elif typeExam == 'cg':
            item = cg_calc(e['value'], patient.birthdate, patient.gender, patient.weight)
        elif typeExam == 'ckd':
            item = ckd_calc(e['value'], patient.birthdate, patient.gender, patient.skinColor)
        elif typeExam == 'swrtz2':
            item = schwartz2_calc(e['value'], patient.height)

        item['date'] = e['date']
        results.append(item)
    return results

@app_pat.route("/exams/<int:admissionNumber>", methods=['GET'])
@jwt_required()
def getExamsbyAdmission(admissionNumber):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    idSegment = request.args.get('idSegment', 1)
    examsList = Exams.findByAdmission(admissionNumber)
    segExam = SegmentExam.refDict(idSegment)
    patient = Patient.findByAdmission(admissionNumber)

    perc = {
        'h_conleuc': {
            'total' : 1,
            'relation': ['h_conlinfoc', 'h_conmono', 'h_coneos', 'h_conbaso', 'h_consegm']
        }
    }

    bufferList = {}
    typeExams = []
    for e in examsList:
        if not e.typeExam.lower() in typeExams and e.typeExam.lower() in segExam:
            key = e.typeExam.lower()
            item = formatExam(e, key, segExam)
            item['name'] = segExam[key].name
            item['perc'] = None
            item['history'] = historyExam(e.typeExam, examsList, segExam)
            item['text'] = False
            bufferList[key] = item
            typeExams.append(key)
            if key in perc:
                perc[key]['total'] = float(e.value)

            if segExam[key].initials.lower() == 'creatinina':
                for keyCalc in ['mdrd','ckd','cg','swrtz2']:
                    if keyCalc in segExam and patient:
                        if keyCalc == 'mdrd':
                            itemCalc = mdrd_calc(e.value, patient.birthdate, patient.gender, patient.skinColor)
                        elif keyCalc == 'cg':
                            itemCalc = cg_calc(e.value, patient.birthdate, patient.gender, patient.weight)
                        elif keyCalc == 'ckd':
                            itemCalc = ckd_calc(e.value, patient.birthdate, patient.gender, patient.skinColor)
                        elif keyCalc == 'swrtz2':
                            itemCalc = schwartz2_calc(e.value, patient.height)

                        if itemCalc['value']:
                            itemCalc['name'] = segExam[keyCalc].name
                            itemCalc['perc'] = None
                            itemCalc['date'] = item['date']
                            itemCalc['history'] = historyCalc(keyCalc, item['history'], patient)
                            bufferList[keyCalc] = itemCalc

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

    examsText = ClinicalNotes.getExamsIfExists(admissionNumber)
    resultsText = {}
    for e in examsText:
        slugExam = slugify(e.prescriber)
        if not slugExam in resultsText.keys():
            resultsText[slugExam] = {
                'name': e.prescriber,
                'text': True,
                'date': e.date.isoformat(),
                'ref': e.text[:20],
                'history': []
            }

        item = {}
        item['date'] = e.date.isoformat()
        item['value'] = e.text
        resultsText[slugExam]['history'].append(item)
        resultsText[slugExam]['date'] = e.date.isoformat()

    return {
        'status': 'success',
        'data': dict(results, **resultsText)
    }, status.HTTP_200_OK


@app_pat.route('/patient/<int:admissionNumber>', methods=['POST'])
@jwt_required()
def setPatientData(admissionNumber):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    data = request.get_json()
    os.environ['TZ'] = 'America/Sao_Paulo'

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

    return tryCommit(db, admissionNumber, user.permission())