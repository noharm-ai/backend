import random
from flask_api import status
from models import db, User, Patient, Prescription, PrescriptionDrug, InterventionReason, Intervention, Segment, setSchema, Exams, PrescriptionPic
from flask import Blueprint, request
from flask_jwt_extended import (create_access_token, create_refresh_token,
                                jwt_required, jwt_refresh_token_required, get_jwt_identity, get_raw_jwt)
from .utils import mdrd_calc, cg_calc, none2zero, formatExam, period, lenghStay, strNone, examAlerts, timeValue
from sqlalchemy import func
from datetime import date, datetime

app_pres = Blueprint('app_pres',__name__)

@app_pres.route("/patients", methods=['GET'])
@app_pres.route("/prescriptions", methods=['GET'])
@app_pres.route("/prescriptions/segments/<int:idSegment>", methods=['GET'])
@app_pres.route("/prescriptions/segments/<int:idSegment>/dept/<int:idDept>", methods=['GET'])
@jwt_required
def getPrescriptions(idSegment=None, idDept=None, idPrescription=None):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    idSegment = request.args.get('idSegment', idSegment)
    idDept = request.args.get('idDept', idDept)
    limit = request.args.get('limit', 250)
    day = request.args.get('date', date.today())

    patients = Patient.getPatients(idSegment=idSegment, idDept=idDept, idPrescription=idPrescription, limit=limit, day=day)
    db.engine.dispose()

    results = []
    for p in patients:

        patient = p[1]
        if (patient is None):
            patient = Patient()
            patient.id = p[0].idPatient
            patient.admissionNumber = p[0].admissionNumber

        tgo, tgp, mdrd, cg, k, na, mg, rni, pcr, ckd, totalAlerts = examAlerts(p, patient)

        results.append({
            'idPrescription': p[0].id,
            'idPatient': p[0].idPatient,
            'name': patient.admissionNumber,
            'admissionNumber': patient.admissionNumber,
            'birthdate': patient.birthdate.isoformat() if patient.birthdate else '',
            'gender': patient.gender,
            'weight': patient.weight if patient.weight else p[0].weight,
            'skinColor': patient.skinColor,
            'lengthStay': lenghStay(patient.admissionDate),
            'date': p[0].date.isoformat(),
            'department': str(p[19]),
            'daysAgo': p[2],
            'prescriptionScore': str(p[3]),
            'scoreOne': str(p[4]),
            'scoreTwo': str(p[5]),
            'scoreThree': str(p[6]),
            'am': str(p[14]),
            'av': str(p[15]),
            'controlled': str(p[16]),
            'np': str(p[20]),
            'tube': str(p[17]),
            'diff': str(p[18]),
            'tgo': tgo,
            'tgp': tgp,
            'mdrd': mdrd,
            'cg': cg,
            'k': k,
            'na': na,
            'mg': mg,
            'rni': rni,
            'pcr': pcr,
            'ckd': ckd,
            'alertExams': totalAlerts,
            'interventions': str(p[21]),
            'patientScore': 'Alto',
            'class': 'yellow', #'red' if p[3] > 12 else 'orange' if p[3] > 8 else 'yellow' if p[3] > 4 else 'green',
            'status': p[0].status,
        })

    return {
        'status': 'success',
        'data': results
    }, status.HTTP_200_OK


@app_pres.route("/prescriptions/status", methods=['GET'])
@jwt_required
def getPrescriptionsStatus(idSegment=1, idDept=None):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    idSegment = request.args.get('idSegment', idSegment)
    idDept = request.args.get('idDept', idDept)
    limit = request.args.get('limit', 250)
    day = request.args.get('date', date.today())

    patients = Patient.getPatients(idSegment=idSegment, idDept=idDept, day=day, limit=limit, onlyStatus=True)
    db.engine.dispose()

    results = []
    for p in patients:
        results.append({
            'idPrescription': p.id,
            'status': p.status
        })

    return {
        'status': 'success',
        'data': results
    }, status.HTTP_200_OK


def getExams(typeExam, idPatient):
    return db.session.query(Exams.value, Exams.unit, Exams.date)\
        .select_from(Exams)\
        .filter(Exams.idPatient == idPatient)\
        .filter(Exams.typeExam == typeExam)\
        .order_by(Exams.date.desc()).limit(1).first()

def getPrevIntervention(idDrug, idPrescription, interventions):
    result = {}
    for i in interventions:
        if i['idDrug'] == idDrug and i['idPrescription'] < idPrescription:
            if 'id' in result.keys() and result['id'] > i['id']: continue
            result = i;
    return result

def getIntervention(idPrescriptionDrug, interventions):
    result = {}
    for i in interventions:
        if i['id'] == idPrescriptionDrug:
            result = i;
    return result

def getDrugType(drugList, pDrugs, checked=False, suspended=False, route=False, source=None, interventions=[]):
    for pd in drugList:

        belong = False
        pd6 = pd[6]

        if pd[0].source is None: pd[0].source = 'Medicamentos'

        if pd[0].source != source: continue
        if checked and (str(pd6) == '1' and bool(pd[0].suspendedDate) == False): belong = True
        if suspended and (bool(pd[0].suspendedDate) == True): belong = True
        if (not checked and not suspended) and (str(pd6) == '0' and bool(pd[0].suspendedDate) == False): belong = True

        if belong:
            pDrugs.append({
                'idPrescriptionDrug': pd[0].id,
                'idDrug': pd[0].idDrug,
                'drug': pd[1].name if pd[1] is not None else 'Medicamento ' + str(pd[0].idDrug),
                'np': pd[1].notdefault if pd[1] is not None else False,
                'am': pd[1].antimicro if pd[1] is not None else False,
                'av': pd[1].mav if pd[1] is not None else False,
                'c': pd[1].controlled if pd[1] is not None else False,
                'dose': pd[0].dose,
                'measureUnit': { 'value': pd[2].id, 'label': pd[2].description } if pd[2] else '',
                'frequency': { 'value': pd[3].id, 'label': pd[3].description } if pd[3] else '',
                'dayFrequency': pd[0].frequency,
                'doseconv': pd[0].doseconv,
                'time': timeValue(pd[0].interval),
                'recommendation': pd[0].notes if pd[0].notes and len(pd[0].notes.strip()) > 0 else None,
                'obs': pd[8],
                'period': period(pd[9]),
                'periodDates': pd[9],
                'route': pd[0].route,
                'grp_solution': pd[0].solutionGroup,
                'stage': 'ACM' if pd[0].solutionACM == 'S' else strNone(pd[0].solutionPhase) + ' x '+ strNone(pd[0].solutionTime) + ' (' + strNone(pd[0].solutionTotalTime) + ')',
                'infusion': strNone(pd[0].solutionDose) + ' ' + strNone(pd[0].solutionUnit),
                'score': str(pd[5]),
                'source': pd[0].source,
                'checked': bool(pd6),
                'intervened': bool(pd[7]),
                'suspended': bool(pd[0].suspendedDate),
                'status': pd[0].status,
                'near': pd[0].near,
                'prevIntervention': getPrevIntervention(pd[0].idDrug, pd[0].idPrescription, interventions),
                'intervention': getIntervention(pd[0].id, interventions)
            })
    return pDrugs

def sortRoute(pDrugs):
    result = [p for p in pDrugs if p['route'] is not None]
    result.extend([p for p in pDrugs if p['route'] is None])
    return result

@app_pres.route('/prescriptions/<int:idPrescription>', methods=['GET'])
@jwt_required
def getPrescription(idPrescription):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    prescription = Prescription.getPrescription(idPrescription)

    if (prescription is None):
        return {}, status.HTTP_204_NO_CONTENT

    patient = prescription[1]
    if (patient is None):
        patient = Patient()
        patient.id = prescription[0].idPatient
        patient.admissionNumber = prescription[0].admissionNumber

    drugs = PrescriptionDrug.findByPrescription(idPrescription, patient.admissionNumber)
    interventions = Intervention.findByAdmission(patient.admissionNumber)
    db.engine.dispose()

    tgo = getExams('TGO', patient.id)
    tgp = getExams('TGP', patient.id)
    cr = getExams('CR', patient.id)
    k = getExams('K', patient.id)
    na = getExams('NA', patient.id)
    mg = getExams('MG', patient.id)
    rni = getExams('PRO', patient.id)
    pcr = getExams('PCRU', patient.id)

    pDrugs = getDrugType(drugs, [], source='Medicamentos', interventions=interventions)
    pDrugs = getDrugType(drugs, pDrugs, checked=True, source='Medicamentos', interventions=interventions)
    pDrugs = getDrugType(drugs, pDrugs, suspended=True, source='Medicamentos', interventions=interventions)
    pDrugs = sortRoute(pDrugs)

    pSolution = getDrugType(drugs, [], source='Soluções', interventions=interventions)
    pSolution = getDrugType(drugs, pSolution, checked=True, source='Soluções', interventions=interventions)
    pSolution = getDrugType(drugs, pSolution, suspended=True, source='Soluções', interventions=interventions)

    pProcedures = getDrugType(drugs, [], source='Proced/Exames', interventions=interventions)
    pProcedures = getDrugType(drugs, pProcedures, checked=True, source='Proced/Exames', interventions=interventions)
    pProcedures = getDrugType(drugs, pProcedures, suspended=True, source='Proced/Exames', interventions=interventions)

    return {
        'status': 'success',
        'data': {
            'idPrescription': prescription[0].id,
            'idSegment': prescription[0].idSegment,
            'idPatient': patient.id,
            'name': prescription[0].admissionNumber,
            'admissionNumber': prescription[0].admissionNumber,
            'birthdate': patient.birthdate.isoformat() if patient.birthdate else '',
            'gender': patient.gender,
            'weight': patient.weight if patient.weight else prescription[0].weight,
            'weightDate': patient.weightDate.isoformat() if patient.weightDate else prescription[0].date.isoformat(),
            'class': random.choice(['green','yellow','red']),
            'skinColor': patient.skinColor,
            'department': prescription[4],
            'tgo': formatExam(tgo, 'tgo'),
            'tgp': formatExam(tgp, 'tgp'),
            'mdrd': mdrd_calc(cr.value, patient.birthdate, patient.gender, patient.skinColor) if cr is not None else '',
            'cg': cg_calc(cr.value, patient.birthdate, patient.gender, patient.weight or prescription[0].weight) if cr is not None else '',
            'ckd': mdrd_calc(cr.value, patient.birthdate, patient.gender, patient.skinColor) if cr is not None else '',
            'creatinina': formatExam(cr, 'cr'),
            'k': formatExam(k, 'k'),
            'na': formatExam(na, 'na'),
            'mg': formatExam(mg, 'mg'),
            'rni': formatExam(rni, 'rni'),
            'pcr': formatExam(pcr, 'pcr'),
            'patientScore': 'High',
            'date': prescription[0].date.isoformat(),
            'daysAgo': prescription[2],
            'prescriptionScore': str(prescription[3]),
            'prescription': pDrugs,
            'solution': pSolution,
            'procedures': pProcedures,
            'interventions': [i for i in interventions if i['idPrescription'] < idPrescription],
            'status': prescription[0].status,
        }
    }, status.HTTP_200_OK


@app_pres.route("/intervention/reasons", methods=['GET'])
@jwt_required
def getInterventionReasons():
    user = User.find(get_jwt_identity())
    setSchema(user.schema)
    results = InterventionReason.findAll()
    db.engine.dispose()

    iList = []
    for i in results:
        iList.append({
            'id': i.id,
            'description': i.description
        })

    return {
        'status': 'success',
        'data': iList
    }, status.HTTP_200_OK


@app_pres.route('/intervention/<int:idPrescriptionDrug>', methods=['PUT'])
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
        i.date = func.now()
        newIntervention = True

    if 'admissionNumber' in data.keys(): i.admissionNumber = data.get('admissionNumber', None)
    if 'idInterventionReason' in data.keys(): i.idInterventionReason = data.get('idInterventionReason', None)
    if 'error' in data.keys(): i.error = data.get('error', None)
    if 'cost' in data.keys(): i.cost = data.get('cost', None)
    if 'observation' in data.keys(): i.notes = data.get('observation', None)
    if 'interactions' in data.keys(): i.interactions = data.get('interactions', None)
    
    i.status = data.get('status', 's')
    i.update = func.now()
    i.user = user.id

    if newIntervention: db.session.add(i)
    setDrugStatus(i.id, i.status)

    try:
        db.session.commit()

        return {
            'status': 'success',
            'data': i.id
        }, status.HTTP_200_OK
    except AssertionError as e:
        db.engine.dispose()

        return {
            'status': 'error',
            'message': str(e)
        }, status.HTTP_400_BAD_REQUEST
    except Exception as e:
        db.engine.dispose()

        return {
            'status': 'error',
            'message': str(e)
        }, status.HTTP_500_INTERNAL_SERVER_ERROR

@app_pres.route('/prescriptions/<int:idPrescription>', methods=['PUT'])
@jwt_required
def setPrescriptionStatus(idPrescription):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    data = request.get_json()

    p = Prescription.query.get(idPrescription)
    p.status = data.get('status', None)
    p.update = func.now()
    p.user = user.id

    ppic = PrescriptionPic.query.get(p.id)
    if ppic is None:
        pObj, code = getPrescriptions(idPrescription=p.id)
        ppic = PrescriptionPic()
        ppic.id = p.id
        ppic.picture = pObj['data'][0]
        db.session.add(ppic)

    try:
        db.session.commit()

        return {
            'status': 'success',
            'data': p.id
        }, status.HTTP_200_OK
    except AssertionError as e:
        db.engine.dispose()

        return {
            'status': 'error',
            'message': str(e)
        }, status.HTTP_400_BAD_REQUEST
    except Exception as e:
        db.engine.dispose()

        return {
            'status': 'error',
            'message': str(e)
        }, status.HTTP_500_INTERNAL_SERVER_ERROR

@app_pres.route('/prescriptions/drug/<int:idPrescriptionDrug>/<int:drugStatus>', methods=['PUT'])
@jwt_required
def setDrugStatus(idPrescriptionDrug, drugStatus):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    pd = PrescriptionDrug.query.get(idPrescriptionDrug)
    pd.status = drugStatus
    pd.update = func.now()
    pd.user = user.id

    ppic = PrescriptionPic.query.get(pd.idPrescription)
    if ppic is None:
        pObj, code = getPrescriptions(idSegment=pd.idSegment, idPrescription=pd.idPrescription)
        ppic = PrescriptionPic()
        ppic.id = pd.idPrescription
        ppic.picture = pObj['data'][0]
        db.session.add(ppic)

    try:
        db.session.commit()

        return {
            'status': 'success',
            'data': pd.id
        }, status.HTTP_200_OK
    except AssertionError as e:
        db.engine.dispose()

        return {
            'status': 'error',
            'message': str(e)
        }, status.HTTP_400_BAD_REQUEST
    except Exception as e:
        db.engine.dispose()

        return {
            'status': 'error',
            'message': str(e)
        }, status.HTTP_500_INTERNAL_SERVER_ERROR