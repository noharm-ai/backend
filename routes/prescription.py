import os
import random
from flask_api import status
from models.main import *
from models.appendix import *
from models.segment import *
from models.prescription import *
from models.notes import ClinicalNotes
from flask import Blueprint, request
from flask_jwt_extended import (create_access_token, create_refresh_token,
                                jwt_required, get_jwt_identity, verify_jwt_in_request)
from .utils import *
from sqlalchemy import func, between
from datetime import date, datetime
from .drugList import DrugList

app_pres = Blueprint('app_pres',__name__)

@app_pres.route("/prescriptions", methods=['GET'])
@jwt_required()
def getPrescriptions():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    idSegment = request.args.get('idSegment', None)
    idDept = request.args.getlist('idDept[]')
    idDrug = request.args.getlist('idDrug[]')
    allDrugs = request.args.get('allDrugs', 0)
    startDate = request.args.get('startDate', str(date.today()))
    endDate = request.args.get('endDate', None)
    pending = request.args.get('pending', 0)
    currentDepartment = request.args.get('currentDepartment', 0)
    agg = request.args.get('agg', 0)
    concilia = request.args.get('concilia', 0)
    discharged = request.args.get('discharged', 0)

    patients = Patient.getPatients(idSegment=idSegment, idDept=idDept, idDrug=idDrug, startDate=startDate, endDate=endDate, pending=pending, agg=agg, currentDepartment=currentDepartment, concilia=concilia, allDrugs=allDrugs, discharged=discharged)

    results = []
    for p in patients:

        patient = p[1]
        if (patient is None):
            patient = Patient()
            patient.idPatient = p[0].idPatient
            patient.admissionNumber = p[0].admissionNumber

        featuresNames = ['alerts','prescriptionScore','scoreOne','scoreTwo','scoreThree',\
                        'am','av','controlled','np','tube','diff','alertExams','interventions','complication']
                        
        features = {'processed':True}
        if p[0].features:
            for f in featuresNames:
                features[f] = p[0].features[f] if f in p[0].features else 0
            
            features['globalScore'] = features['prescriptionScore'] + features['av'] + features['alertExams'] + features['alerts'] + features['diff']
            if features['globalScore'] > 90 : features['class'] = 'red'
            elif features['globalScore'] > 60 : features['class'] = 'orange'
            elif features['globalScore'] > 10 : features['class'] = 'yellow'
            else: features['class'] = 'green'
        else:
            features['processed'] = False
            features['globalScore'] = 0
            features['class'] = 'blue'

        results.append(dict(features, **{
            'idPrescription': str(p[0].id),
            'idPatient': p[0].idPatient,
            'name': patient.admissionNumber,
            'admissionNumber': patient.admissionNumber,
            'birthdate': patient.birthdate.isoformat() if patient.birthdate else None,
            'gender': patient.gender,
            'weight': patient.weight,
            'skinColor': patient.skinColor,
            'lengthStay': lenghStay(patient.admissionDate),
            'dischargeDate': patient.dischargeDate.isoformat() if patient.dischargeDate else None,
            'date': p[0].date.isoformat(),
            'department': str(p[2]),
            'status': p[0].status
        }))

    return {
        'status': 'success',
        'data': results
    }, status.HTTP_200_OK

@app_pres.route('/prescriptions/<int:idPrescription>', methods=['GET'])
@jwt_required()
def getPrescriptionAuth(idPrescription):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    p = Prescription.getPrescription(idPrescription)

    if (p is None):
        return { 'status': 'error', 'message': 'Prescrição Inexistente!' }, status.HTTP_400_BAD_REQUEST

    if p[0].agg:
        return getPrescription(idPrescription=idPrescription, admissionNumber=p[0].admissionNumber, aggDate=p[0].date, idSegment=p[0].idSegment)
    else:
        return getPrescription(idPrescription=idPrescription)

def buildHeaders(headers, pDrugs, pSolution, pProcedures):
    for pid in headers.keys():
        drugs = [d for d in pDrugs if int(d['idPrescription']) == pid]
        drugsInterv = [d['prevIntervention'] for d in drugs if d['prevIntervention'] != {}]

        solutions = [s for s in pSolution if int(s['idPrescription']) == pid]
        solutionsInterv = [s['prevIntervention'] for s in solutions if s['prevIntervention'] != {}]
        
        procedures = [p for p in pProcedures if int(p['idPrescription']) == pid]
        proceduresInterv = [p['prevIntervention'] for p in procedures if p['prevIntervention'] != {}]
        
        headers[pid]['drugs'] = getFeatures({'data':{'prescription':drugs, 'solution': [], 'procedures': [], 'interventions':drugsInterv, 'alertExams':[], 'complication': 0}})
        headers[pid]['solutions'] = getFeatures({'data':{'prescription':[], 'solution': solutions, 'procedures': [], 'interventions':solutionsInterv, 'alertExams':[], 'complication': 0}})
        headers[pid]['procedures'] = getFeatures({'data':{'prescription':[], 'solution': [], 'procedures': procedures, 'interventions':proceduresInterv, 'alertExams':[], 'complication': 0}})

    return headers

def getPrevIntervention(interventions, dtPrescription):
    result = False
    for i in interventions:
        if int(i['id']) == 0 and i['status'] == 's' and i['dateTime'] < dtPrescription:
            result = True;
    return result

def getExistIntervention(interventions, dtPrescription):
    result = False
    for i in interventions:
        if int(i['id']) == 0 and i['dateTime'] < dtPrescription:
            result = True;
    return result

def getPrescription(idPrescription=None, admissionNumber=None, aggDate=None, idSegment=None):

    if idPrescription:
        prescription = Prescription.getPrescription(idPrescription)
    else:
        prescription = Prescription.getPrescriptionAgg(admissionNumber, aggDate, idSegment)

    if (prescription is None):
        return { 'status': 'error', 'message': 'Prescrição Inexistente!' }, status.HTTP_400_BAD_REQUEST

    patient = prescription[1]
    if (patient is None):
        patient = Patient()
        patient.idPatient = prescription[0].idPatient
        patient.admissionNumber = prescription[0].admissionNumber

    lastDept = Prescription.lastDeptbyAdmission(prescription[0].id, patient.admissionNumber)
    drugs = PrescriptionDrug.findByPrescription(prescription[0].id, patient.admissionNumber, aggDate, idSegment)
    interventions = Intervention.findAll(admissionNumber=patient.admissionNumber)
    relations = Prescription.findRelation(prescription[0].id,patient.admissionNumber, aggDate)
    headers = Prescription.getHeaders(admissionNumber, aggDate, idSegment) if aggDate else []

    clinicalNotesCount = ClinicalNotes.getCountIfExists(prescription[0].admissionNumber)
    notesSigns = None
    notesInfo = None
    if clinicalNotesCount[0]:
        notesSigns = ClinicalNotes.getSigns(prescription[0].admissionNumber)
        notesInfo = ClinicalNotes.getInfo(prescription[0].admissionNumber)

    exams = Exams.findLatestByAdmission(patient, prescription[0].idSegment)
    age = data2age(patient.birthdate.isoformat() if patient.birthdate else date.today().isoformat())

    examsJson = []
    alertExams = 0
    for e in exams:
        examsJson.append({'key': e, 'value': exams[e]})
        alertExams += int(exams[e]['alert'])

    exams = dict(exams, **{
        'age': age,
        'weight': patient.weight,
    })

    drugList = DrugList(drugs, interventions, relations, exams, aggDate is not None)

    pDrugs = drugList.getDrugType([], 'Medicamentos') #refactor sort
    pDrugs = drugList.getDrugType(pDrugs, 'Medicamentos', checked=True) #refactor sort
    pDrugs = drugList.getDrugType(pDrugs, 'Medicamentos', suspended=True) #refactor sort
    pDrugs.sort(key=drugList.sortDrugs)
    pDrugs = drugList.sortWhiteList(pDrugs)
    
    conciliaList = []
    if prescription[0].concilia:
        pDrugs = drugList.changeDrugName(pDrugs)
        conciliaDrugsT = PrescriptionDrug.findByPrescription(prescription[0].id, patient.admissionNumber, date.today(), prescription[0].idSegment)
        conciliaDrugsY = PrescriptionDrug.findByPrescription(prescription[0].id, patient.admissionNumber, (date.today() - timedelta(days=1)), prescription[0].idSegment)
        conciliaList = drugList.conciliaList(conciliaDrugsT, [])
        conciliaList = drugList.conciliaList(conciliaDrugsY,conciliaList)

    pSolution = drugList.getDrugType([], 'Soluções')
    pInfusion = drugList.getInfusionList()

    pProcedures = drugList.getDrugType([], 'Proced/Exames')
    pProcedures = drugList.getDrugType(pProcedures, 'Proced/Exames', checked=True)
    pProcedures = drugList.getDrugType(pProcedures, 'Proced/Exames', suspended=True)

    pDiet = drugList.getDrugType([], 'Dietas')
    pDiet = drugList.getDrugType(pDiet, 'Dietas', checked=True)
    pDiet = drugList.getDrugType(pDiet, 'Dietas', suspended=True)

    drugList.sumAlerts()

    if aggDate:
        headers = buildHeaders(headers, pDrugs,pSolution,pProcedures)

        if verify_jwt_in_request(optional=True):
            user = User.find(get_jwt_identity())
            if user.cpoe():
                pDrugs = drugList.cpoeDrugs(pDrugs, idPrescription)
                pDrugs = drugList.sortWhiteList(pDrugs)
                pSolution = drugList.cpoeDrugs(pSolution, idPrescription)
                pProcedures = drugList.cpoeDrugs(pProcedures, idPrescription)
                pDiet = drugList.cpoeDrugs(pDiet, idPrescription)

    pIntervention = [i for i in interventions if int(i['id']) == 0 and int(i['idPrescription']) == prescription[0].id]

    return {
        'status': 'success',
        'data': {
            'idPrescription': str(prescription[0].id),
            'idSegment': prescription[0].idSegment,
            'segmentName': prescription[5],
            'idPatient': prescription[0].idPatient,
            'idHospital': prescription[0].idHospital,
            'name': prescription[0].admissionNumber,
            'agg': prescription[0].agg,
            'concilia': prescription[0].concilia,
            'conciliaList': conciliaList,
            'admissionNumber': prescription[0].admissionNumber,
            'admissionDate': patient.admissionDate.isoformat() if patient.admissionDate else None,
            'birthdate': patient.birthdate.isoformat() if patient.birthdate else None,
            'gender': patient.gender,
            'height': patient.height,
            'weight': patient.weight,
            'observation': prescription[6],
            'notes': prescription[7],
            'alert': prescription[8],
            'alertExpire': patient.alertExpire.isoformat() if patient.alertExpire else None,
            'age': age,
            'weightUser': bool(patient.user),
            'weightDate': patient.weightDate.isoformat() if patient.weightDate else None,
            'dischargeDate': patient.dischargeDate.isoformat() if patient.dischargeDate else None,
            'dischargeReason': patient.dischargeReason,
            'bed': prescription[0].bed,
            'record': prescription[0].record,
            'class': random.choice(['green','yellow','red']),
            'skinColor': patient.skinColor,
            'department': prescription[4],
            'lastDepartment': lastDept[0] if lastDept else None,
            'patientScore': 'High',
            'date': prescription[0].date.isoformat(),
            'expire': prescription[0].expire.isoformat() if prescription[0].expire else None,
            'prescription': pDrugs,
            'solution': pSolution,
            'procedures': pProcedures,
            'infusion': pInfusion,
            'diet': pDiet,
            'interventions': interventions,
            'alertExams': alertExams,
            'exams': examsJson[:10],
            'status': prescription[0].status,
            'prescriber': prescription[9],
            'headers': headers,
            'intervention': pIntervention[0] if len(pIntervention) else None,
            'prevIntervention': getPrevIntervention(interventions, prescription[0].date),
            'existIntervention': getExistIntervention(interventions, prescription[0].date),
            'clinicalNotes': clinicalNotesCount[9],
            'complication': clinicalNotesCount[2],
            'notesSigns': strNone(notesSigns[0]) if notesSigns else '',
            'notesSignsDate': notesSigns[1].isoformat() if notesSigns else None,
            'notesInfo': strNone(notesInfo[0]) if notesInfo else '',
            'notesInfoDate': notesInfo[1].isoformat() if notesInfo else None,
            'clinicalNotesStats': {
                'medications': clinicalNotesCount[1],
                'complication': clinicalNotesCount[2],
                'symptoms': clinicalNotesCount[3],
                'diseases': clinicalNotesCount[4],
                'info': clinicalNotesCount[5],
                'conduct': clinicalNotesCount[6],
                'signs': clinicalNotesCount[7],
                'allergy': clinicalNotesCount[8],
                'total': clinicalNotesCount[9],
            },
            'alertStats': drugList.alertStats,
            'features': prescription[0].features,
            'user': prescription[10],
        }
    }, status.HTTP_200_OK

@app_pres.route('/prescriptions/<int:idPrescription>', methods=['PUT'])
@jwt_required()
def setPrescriptionStatus(idPrescription):
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ['TZ'] = 'America/Sao_Paulo'

    p = Prescription.query.get(idPrescription)
    if (p is None):
        return { 'status': 'error', 'message': 'Prescrição Inexistente!' }, status.HTTP_400_BAD_REQUEST

    if 'status' in data.keys(): 
        p.status = data.get('status', None)
        p.update = datetime.today()
        if p.agg:
            db.session.query(Prescription)\
                      .filter(Prescription.admissionNumber == p.admissionNumber)\
                      .filter(Prescription.status != p.status)\
                      .filter(Prescription.idSegment == p.idSegment)\
                      .filter(Prescription.concilia == None)\
                      .filter(between(func.date(p.date), func.date(Prescription.date), func.date(Prescription.expire)))\
                      .update({
                        'status': p.status,
                        'update': datetime.today(),
                        'user': user.id
                      }, synchronize_session='fetch')
        else:
            Prescription.checkPrescriptions(p.admissionNumber, p.date, p.idSegment, user.id)

    if 'notes' in data.keys(): 
        p.notes = data.get('notes', None)
        p.notes_at = datetime.today()

    if 'concilia' in data.keys(): 
        concilia = data.get('concilia', 's')
        p.concilia = str(concilia)[:1]

    p.user = user.id

    return tryCommit(db, str(idPrescription), user.permission())

@app_pres.route("/prescriptions/drug/<int:idPrescriptionDrug>/period", methods=['GET'])
@jwt_required()
def getDrugPeriod(idPrescriptionDrug):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    future = request.args.get('future', None)
    results = [{1: []}]

    if idPrescriptionDrug != 0:
        results, admissionHistory = PrescriptionDrug.findByPrescriptionDrug(idPrescriptionDrug, future)
    else:
        results[0][1].append('Intervenção no paciente não tem medicamento associado.')

    if future and len(results[0][1]) == 0:
        if admissionHistory:
            results[0][1].append('Não há prescrição posterior para esse Medicamento')
        else:
            results[0][1].append('Não há prescrição posterior para esse Paciente')

    periodList = results[0][1]
    for i, p in enumerate(periodList):
        p = p.replace('33x','SNx')
        p = p.replace('44x','ACMx')
        p = p.replace('55x','CONTx')
        p = p.replace('66x','AGORAx')
        p = p.replace('99x','N/Dx')
        periodList[i] = p

    return {
        'status': 'success',
        'data': periodList
    }, status.HTTP_200_OK

@app_pres.route('/prescriptions/drug/<int:idPrescriptionDrug>', methods=['PUT'])
@jwt_required()
def setPrescriptionDrugNote(idPrescriptionDrug):
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ['TZ'] = 'America/Sao_Paulo'

    if 'notes' in data:
        notes = data.get('notes', None)
        idDrug = data.get('idDrug', None)
        admissionNumber = data.get('admissionNumber', None)
        note = Notes.query.get((0, idPrescriptionDrug))
        newObs = False

        if note is None:
            newObs = True
            note = Notes()
            note.idPrescriptionDrug = idPrescriptionDrug
            note.idOutlier = 0

        note.idDrug = idDrug
        note.admissionNumber = admissionNumber
        note.notes = notes
        note.update = datetime.today()
        note.user  = user.id

        if newObs: db.session.add(note)

    return tryCommit(db, str(idPrescriptionDrug), user.permission())

@app_pres.route('/prescriptions/<int:idPrescription>/update', methods=['GET'])
@jwt_required()
def getPrescriptionUpdate(idPrescription):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    p = Prescription.query.get(idPrescription)
    if (p is None):
        return { 'status': 'error', 'message': 'Prescrição Inexistente!' }, status.HTTP_400_BAD_REQUEST

    if p.agg:
        query = "INSERT INTO " + user.schema + ".presmed \
                    SELECT pm.*\
                    FROM " + user.schema + ".presmed pm\
                    WHERE fkprescricao IN (\
                        SELECT fkprescricao\
                        FROM " + user.schema + ".prescricao p\
                        WHERE p.nratendimento = " + str(p.admissionNumber) + "\
                        AND p.idsegmento IS NOT NULL \
                        AND (\
                            p.dtprescricao::date = '" + str(p.date) + "'::date OR\
                            p.dtvigencia::date = '" + str(p.date) + "'::date\
                        )\
                    );"  
    else:
        query = "INSERT INTO " + user.schema + ".presmed \
                    SELECT *\
                    FROM " + user.schema + ".presmed\
                    WHERE fkprescricao = " + str(int(idPrescription)) + ";"

    db.engine.execute(query)

    return tryCommit(db, str(idPrescription))