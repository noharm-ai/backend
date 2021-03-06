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
                                jwt_required, jwt_refresh_token_required, get_jwt_identity, get_raw_jwt)
from .utils import *
from sqlalchemy import func
from datetime import date, datetime

app_pres = Blueprint('app_pres',__name__)

@app_pres.route("/prescriptions", methods=['GET'])
@jwt_required
def getPrescriptions():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    idSegment = request.args.get('idSegment', None)
    idDept = request.args.getlist('idDept[]')
    idDrug = request.args.getlist('idDrug[]')
    startDate = request.args.get('startDate', str(date.today()))
    endDate = request.args.get('endDate', None)
    pending = request.args.get('pending', 0)
    currentDepartment = request.args.get('currentDepartment', 0)
    agg = request.args.get('agg', 0)

    patients = Patient.getPatients(idSegment=idSegment, idDept=idDept, idDrug=idDrug, startDate=startDate, endDate=endDate, pending=pending, agg=agg, currentDepartment=currentDepartment)

    results = []
    for p in patients:

        patient = p[1]
        if (patient is None):
            patient = Patient()
            patient.idPatient = p[0].idPatient
            patient.admissionNumber = p[0].admissionNumber

        featuresNames = ['alerts','prescriptionScore','scoreOne','scoreTwo','scoreThree',\
                        'am','av','controlled','np','tube','diff','alertExams','interventions']
                        
        features = {'processed':True}
        if p[0].features:
            for f in featuresNames:
                features[f] = p[0].features[f] if f in p[0].features else 0
            
            features['globalScore'] = features['prescriptionScore'] + features['av'] + features['alertExams'] + features['alerts']
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

class DrugList():

    def __init__(self, drugList, interventions, relations, exams, agg):
        self.drugList = drugList
        self.interventions = interventions
        self.relations = relations
        self.exams = exams
        self.agg = agg
        self.maxDoseAgg = {}

    def getPrevIntervention(self, idDrug, idPrescription):
        result = {}
        for i in self.interventions:
            if i['idDrug'] == idDrug and i['status'] == 's' and i['idPrescription'] < idPrescription:
                if 'id' in result.keys() and result['id'] > i['id']: continue
                result = i;
        return result

    def getExistIntervention(self, idDrug, idPrescription):
        result = False
        for i in self.interventions:
            if i['idDrug'] == idDrug and i['idPrescription'] < idPrescription:
                result = True;
        return result

    def getIntervention(self, idPrescriptionDrug):
        result = {}
        for i in self.interventions:
            if i['id'] == idPrescriptionDrug:
                result = i;
        return result

    def getDrugType(self, pDrugs, source, checked=False, suspended=False):
        for pd in self.drugList:

            belong = False
            if pd[0].source is None: pd[0].source = 'Medicamentos'
            if pd[0].source != source: continue
            if source == 'Soluções': belong = True
            if checked and bool(pd[0].checked) == True and bool(pd[0].suspendedDate) == False: belong = True
            if suspended and (bool(pd[0].suspendedDate) == True): belong = True
            if (not checked and not suspended) and (bool(pd[0].checked) == False and bool(pd[0].suspendedDate) == False): belong = True

            if not belong: continue

            pdFrequency = 1 if pd[0].frequency in [33,44,55,66,99] else pd[0].frequency
            pdDoseconv = none2zero(pd[0].doseconv) * none2zero(pdFrequency)
            pdUnit = strNone(pd[2].id) if pd[2] else ''
            pdWhiteList = bool(pd[6].whiteList) if pd[6] is not None else False
            doseWeightStr = None
            expireDay = pd[10].day if pd[10] else 0

            idDrugAgg = pd[0].idDrug * 10 + expireDay
            if idDrugAgg not in self.maxDoseAgg:
                self.maxDoseAgg[idDrugAgg] = {'value': 0, 'count': 0}

            self.maxDoseAgg[idDrugAgg]['value'] += pdDoseconv
            self.maxDoseAgg[idDrugAgg]['count'] += 1

            tubeAlert = False
            alerts = []
            if not bool(pd[0].suspendedDate):
                if self.exams and pd[6]:
                    if pd[6].kidney and 'ckd' in self.exams and self.exams['ckd']['value'] and pd[6].kidney > self.exams['ckd']['value']:
                        alerts.append('Medicamento deve sofrer ajuste de posologia ou contraindicado, já que a função renal do paciente (' + str(self.exams['ckd']['value']) + ' mL/min) está abaixo de ' + str(pd[6].kidney) + ' mL/min.')

                    if pd[6].liver:
                        if ('tgp' in self.exams and self.exams['tgp']['value'] and float(self.exams['tgp']['value']) > pd[6].liver) or ('tgo' in self.exams and self.exams['tgo']['value'] and float(self.exams['tgo']['value']) > pd[6].liver):
                            alerts.append('Medicamento deve sofrer ajuste de posologia ou contraindicado, já que a função hepática do paciente está reduzida (acima de ' + str(pd[6].liver) + ' U/L).')

                    if pd[6].platelets and 'plqt' in self.exams and self.exams['plqt']['value'] and pd[6].platelets > self.exams['plqt']['value']:
                        alerts.append('Medicamento contraindicado para paciente com plaquetas (' + str(self.exams['plqt']['value']) + ' plaquetas/µL) abaixo de ' + str(pd[6].platelets) + ' plaquetas/µL.')

                    if pd[6].elderly and self.exams['age'] > 60:
                        alerts.append('Medicamento potencialmente inapropriado para idosos, independente das comorbidades do paciente.')

                    if pd[6].useWeight:
                        weight = none2zero(self.exams['weight'])
                        weight = weight if weight > 0 else 1

                        doseWeight = round(pd[0].dose / float(weight),2)
                        doseWeightStr = str(doseWeight) + ' ' + pdUnit + '/Kg'

                        keyDrugKg = str(idDrugAgg)+'kg'
                        if keyDrugKg not in self.maxDoseAgg:
                            self.maxDoseAgg[keyDrugKg] = {'value': 0, 'count': 0}

                        self.maxDoseAgg[keyDrugKg]['value'] += doseWeight
                        self.maxDoseAgg[keyDrugKg]['count'] += 1 

                        if pd[6].idMeasureUnit != None and pd[6].idMeasureUnit != pdUnit:
                            doseWeightStr += ' ou ' + str(pd[0].doseconv) + ' ' + str(pd[6].idMeasureUnit) + '/Kg (faixa arredondada)'

                        if pd[6].maxDose and pd[6].maxDose < doseWeight:
                            alerts.append('Dose diária prescrita (' + str(doseWeight) + ' ' + str(pd[6].idMeasureUnit) + '/Kg) maior que a dose de alerta (' + str(pd[6].maxDose) + ' ' + str(pd[6].idMeasureUnit) + '/Kg) usualmente recomendada (considerada a dose diária independente da indicação).')

                        if pd[6].maxDose and self.maxDoseAgg[keyDrugKg]['count'] > 1 and pd[6].maxDose < self.maxDoseAgg[keyDrugKg]['value']:
                            alerts.append('Dose diária prescrita SOMADA (' + str(self.maxDoseAgg[keyDrugKg]['value']) + ' ' + str(pd[6].idMeasureUnit) + '/Kg) maior que a dose de alerta (' + str(pd[6].maxDose) + ' ' + str(pd[6].idMeasureUnit) + '/Kg) usualmente recomendada (considerada a dose diária independente da indicação).')

                    else:

                        if pd[6].maxDose and pd[6].maxDose < pdDoseconv:
                            alerts.append('Dose diária prescrita (' + str(pdDoseconv) + ' ' + str(pd[6].idMeasureUnit) + ') maior que a dose de alerta (' + str(pd[6].maxDose) + ' ' + str(pd[6].idMeasureUnit) + ') usualmente recomendada (considerada a dose diária independente da indicação).')

                        if pd[6].maxDose and self.maxDoseAgg[idDrugAgg]['count'] > 1 and pd[6].maxDose < self.maxDoseAgg[idDrugAgg]['value']:
                            alerts.append('Dose diária prescrita SOMADA (' + str(self.maxDoseAgg[idDrugAgg]['value']) + ' ' + str(pd[6].idMeasureUnit) + ') maior que a dose de alerta (' + str(pd[6].maxDose) + ' ' + str(pd[6].idMeasureUnit) + ') usualmente recomendada (considerada a dose diária independente da indicação).')

                if pd[6] and pd[6].tube and pd[0].tube:
                    alerts.append('Medicamento contraindicado via sonda (' + strNone(pd[0].route) + ')')
                    tubeAlert = True

                if pd[0].alergy == 'S':
                    alerts.append('Paciente alérgico a este medicamento.')

                if pd[6] and pd[6].maxTime and pd[0].period and pd[0].period > pd[6].maxTime:
                    alerts.append('Tempo de tratamento atual (' + str(pd[0].period) + ' dias) maior que o tempo máximo de tratamento (' + str(pd[6].maxTime) + ' dias) usualmente recomendado.')

                if pd[0].id in self.relations:
                    for a in self.relations[pd[0].id]:
                        alerts.append(a)       

            pDrugs.append({
                'idPrescription': pd[0].idPrescription,
                'idPrescriptionDrug': pd[0].id,
                'idDrug': pd[0].idDrug,
                'drug': pd[1].name if pd[1] is not None else 'Medicamento ' + str(pd[0].idDrug),
                'np': pd[6].notdefault if pd[6] is not None else False,
                'am': pd[6].antimicro if pd[6] is not None else False,
                'av': pd[6].mav if pd[6] is not None else False,
                'c': pd[6].controlled if pd[6] is not None else False,
                'whiteList': pdWhiteList,
                'doseWeight': doseWeightStr,
                'dose': pd[0].dose,
                'measureUnit': { 'value': pd[2].id, 'label': pd[2].description } if pd[2] else '',
                'frequency': { 'value': pd[3].id, 'label': pd[3].description } if pd[3] else '',
                'dayFrequency': pd[0].frequency,
                'doseconv': pd[0].doseconv,
                'time': timeValue(pd[0].interval),
                'recommendation': pd[0].notes if pd[0].notes and len(pd[0].notes.strip()) > 0 else None,
                'period': str(pd[0].period) + 'D' if pd[0].period else '',
                'periodDates': [],
                'route': pd[0].route,
                'grp_solution': pd[0].solutionGroup,
                'stage': 'ACM' if pd[0].solutionACM == 'S' else strNone(pd[0].solutionPhase) + ' x '+ strNone(pd[0].solutionTime) + ' (' + strNone(pd[0].solutionTotalTime) + ')',
                'infusion': strNone(pd[0].solutionDose) + ' ' + strNone(pd[0].solutionUnit),
                'score': str(pd[5]) if not pdWhiteList else '0',
                'source': pd[0].source,
                'checked': bool(pd[0].checked or pd[9] == 's'),
                'suspended': bool(pd[0].suspendedDate),
                'status': pd[0].status,
                'near': pd[0].near,
                'prevIntervention': self.getPrevIntervention(pd[0].idDrug, pd[0].idPrescription),
                'existIntervention': self.getExistIntervention(pd[0].idDrug, pd[0].idPrescription),
                'intervention': self.getIntervention(pd[0].id),
                'alerts': alerts,
                'tubeAlert': tubeAlert,
                'notes': pd[7],
                'prevNotes': pd[8]
            })
        return pDrugs

    def sortWhiteList(self, pDrugs):
        result = [p for p in pDrugs if p['whiteList'] is False]
        result.extend([p for p in pDrugs if p['whiteList']])
        return result

    def getInfusionList(self):
        result = {}
        for pd in self.drugList:
            if pd[0].solutionGroup and pd[0].source == 'Soluções':
                
                pdID = pd[0].idPrescription
                pdGroup = pd[0].solutionGroup

                if not pdID in result:
                    result[pdID] = {}
                if not pdGroup in result[pdID].keys():
                    result[pdID][pdGroup] = {'totalVol' : 0, 'amount': 0, 'vol': 0, 'speed': 0, 'unit': 'ml'}

                pdDose = pd[0].dose

                if pd[6] and pd[6].amount and pd[6].amountUnit:
                    result[pdID][pdGroup]['vol'] = pdDose
                    result[pdID][pdGroup]['amount'] = pd[6].amount
                    result[pdID][pdGroup]['unit'] = pd[6].amountUnit

                    if pd[2].id.lower() != 'ml' and pd[2].id.lower() == pd[6].amountUnit.lower():
                        result[pdID][pdGroup]['vol'] = pdDose = round(pd[0].dose / pd[6].amount,2)

                result[pdID][pdGroup]['speed'] = pd[0].solutionDose
                result[pdID][pdGroup]['totalVol'] += pdDose
                result[pdID][pdGroup]['totalVol'] = round(result[pdID][pdGroup]['totalVol'],2)

        return result


@app_pres.route('/prescriptions/<int:idPrescription>', methods=['GET'])
@jwt_required
def getPrescriptionAuth(idPrescription):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    p = Prescription.getPrescription(idPrescription)

    if (p is None):
        return { 'status': 'error', 'message': 'Prescrição Inexistente!' }, status.HTTP_400_BAD_REQUEST

    if p[0].agg:
        return getPrescription(idPrescription=idPrescription, admissionNumber=p[0].admissionNumber, aggDate=p[0].date)
    else:
        return getPrescription(idPrescription=idPrescription)

def sortDrugs(d):
  return d['drug'].lower()

def buildHeaders(headers, pDrugs, pSolution, pProcedures):
    for pid in headers.keys():
        drugs = [d for d in pDrugs if d['idPrescription'] == pid]
        drugsInterv = [d['prevIntervention'] for d in drugs if d['prevIntervention'] != {}]

        solutions = [s for s in pSolution if s['idPrescription'] == pid]
        solutionsInterv = [s['prevIntervention'] for s in solutions if s['prevIntervention'] != {}]
        
        procedures = [p for p in pProcedures if p['idPrescription'] == pid]
        proceduresInterv = [s['prevIntervention'] for s in solutions if s['prevIntervention'] != {}]
        
        headers[pid]['drugs'] = getFeatures({'data':{'prescription':drugs, 'solution': [], 'procedures': [], 'interventions':drugsInterv, 'alertExams':[]}})
        headers[pid]['solutions'] = getFeatures({'data':{'prescription':[], 'solution': solutions, 'procedures': [], 'interventions':solutionsInterv, 'alertExams':[]}})
        headers[pid]['procedures'] = getFeatures({'data':{'prescription':[], 'solution': [], 'procedures': procedures, 'interventions':proceduresInterv, 'alertExams':[]}})

    return headers

def getPrevIntervention(interventions, dtPrescription):
    result = False
    for i in interventions:
        if i['id'] == 0 and i['status'] == 's' and i['dateTime'] < dtPrescription:
            result = True;
    return result

def getExistIntervention(interventions, dtPrescription):
    result = False
    for i in interventions:
        if i['id'] == 0 and i['dateTime'] < dtPrescription:
            result = True;
    return result

def getPrescription(idPrescription=None, admissionNumber=None, aggDate=None):

    if idPrescription:
        prescription = Prescription.getPrescription(idPrescription)
    else:
        prescription = Prescription.getPrescriptionAgg(admissionNumber, aggDate)

    if (prescription is None):
        return { 'status': 'error', 'message': 'Prescrição Inexistente!' }, status.HTTP_400_BAD_REQUEST

    patient = prescription[1]
    if (patient is None):
        patient = Patient()
        patient.idPatient = prescription[0].idPatient
        patient.admissionNumber = prescription[0].admissionNumber

    lastDept = Prescription.lastDeptbyAdmission(prescription[0].id, patient.admissionNumber)
    drugs = PrescriptionDrug.findByPrescription(prescription[0].id, patient.admissionNumber, aggDate)
    interventions = Intervention.findAll(admissionNumber=patient.admissionNumber)
    relations = Prescription.findRelation(prescription[0].id,patient.admissionNumber, aggDate)
    headers = Prescription.getHeaders(admissionNumber, aggDate) if aggDate else []

    clinicalNotes = ClinicalNotes.getIfExists(prescription[0].admissionNumber)

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

    pDrugs = drugList.getDrugType([], 'Medicamentos')
    pDrugs = drugList.getDrugType(pDrugs, 'Medicamentos', checked=True)
    pDrugs = drugList.getDrugType(pDrugs, 'Medicamentos', suspended=True)
    pDrugs.sort(key=sortDrugs)
    pDrugs = drugList.sortWhiteList(pDrugs)

    pSolution = drugList.getDrugType([], 'Soluções')
    pInfusion = drugList.getInfusionList()

    pProcedures = drugList.getDrugType([], 'Proced/Exames')
    pProcedures = drugList.getDrugType(pProcedures, 'Proced/Exames', checked=True)
    pProcedures = drugList.getDrugType(pProcedures, 'Proced/Exames', suspended=True)

    if aggDate:
        headers = buildHeaders(headers, pDrugs,pSolution,pProcedures)

    pIntervention = [i for i in interventions if i['id'] == 0 and i['idPrescription'] == prescription[0].id]

    return {
        'status': 'success',
        'data': {
            'idPrescription': str(prescription[0].id),
            'idSegment': prescription[0].idSegment,
            'segmentName': prescription[5],
            'idPatient': prescription[0].idPatient,
            'name': prescription[0].admissionNumber,
            'agg': prescription[0].agg,
            'admissionNumber': prescription[0].admissionNumber,
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
            'interventions': interventions,
            'alertExams': alertExams,
            'exams': examsJson[:10],
            'status': prescription[0].status,
            'prescriber': prescription[9],
            'headers': headers,
            'intervention': pIntervention[0] if len(pIntervention) else None,
            'prevIntervention': getPrevIntervention(interventions, prescription[0].date),
            'existIntervention': getExistIntervention(interventions, prescription[0].date),
            'clinicalNotes': clinicalNotes
        }
    }, status.HTTP_200_OK

@app_pres.route('/prescriptions/<int:idPrescription>', methods=['PUT'])
@jwt_required
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
                      .filter(Prescription.idSegment != None)\
                      .filter(or_(
                         func.date(Prescription.date) == func.date(p.date),
                         func.date(Prescription.expire) == func.date(p.date)
                      ))\
                      .update({
                        'status': p.status,
                        'update': datetime.today(),
                        'user': user.id
                      }, synchronize_session='fetch')

    if 'notes' in data.keys(): 
        p.notes = data.get('notes', None)
        p.notes_at = datetime.today()

    p.user = user.id

    return tryCommit(db, str(idPrescription), user.permission())

@app_pres.route("/prescriptions/drug/<int:idPrescriptionDrug>/period", methods=['GET'])
@jwt_required
def getDrugPeriod(idPrescriptionDrug):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    future = request.args.get('future', None)
    results, admissionHistory = PrescriptionDrug.findByPrescriptionDrug(idPrescriptionDrug, future)

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
@jwt_required
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

    return tryCommit(db, idPrescriptionDrug, user.permission())

@app_pres.route('/prescriptions/<int:idPrescription>/update', methods=['GET'])
@jwt_required
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