import random, copy
from flask_api import status
from models import db, User, Patient, Prescription, PrescriptionDrug, InterventionReason,\
                    Intervention, Segment, setSchema, Exams, PrescriptionPic, DrugAttributes,\
                    Notes
from flask import Blueprint, request
from flask_jwt_extended import (create_access_token, create_refresh_token,
                                jwt_required, jwt_refresh_token_required, get_jwt_identity, get_raw_jwt)
from .utils import mdrd_calc, cg_calc, ckd_calc, none2zero, formatExam,\
                    period, lenghStay, strNone, examAlerts, timeValue,\
                    data2age, examEmpty, is_float, examsName, tryCommit
from sqlalchemy import func
from datetime import date, datetime

app_pres = Blueprint('app_pres',__name__)

@app_pres.route("/prescriptions", methods=['GET'])
@jwt_required
def getPrescriptions(idPrescription=None):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    print(request.args)

    idSegment = request.args.get('idSegment', None)
    idDept = request.args.getlist('idDept[]')
    idDrug = request.args.getlist('idDrug[]')
    limit = request.args.get('limit', 250)
    day = request.args.get('date', date.today())

    patients = Patient.getPatients(idSegment=idSegment, idDept=idDept, idDrug=idDrug, idPrescription=idPrescription, limit=limit, day=day)
    db.engine.dispose()

    results = []
    for p in patients:

        patient = p[1]
        if (patient is None):
            patient = Patient()
            patient.idPatient = p[0].idPatient
            patient.admissionNumber = p[0].admissionNumber

        tgo, tgp, cr, mdrd, cg, k, na, mg, rni, pcr, ckd, totalAlerts = examAlerts(p, patient)

        results.append({
            'idPrescription': p[0].id,
            'idPatient': p[0].idPatient,
            'name': patient.admissionNumber,
            'admissionNumber': patient.admissionNumber,
            'birthdate': patient.birthdate.isoformat() if patient.birthdate else '',
            'gender': patient.gender,
            'weight': patient.weight,
            'skinColor': patient.skinColor,
            'lengthStay': lenghStay(patient.admissionDate),
            'date': p[0].date.isoformat(),
            'department': str(p[19]),
            'daysAgo': p[2],
            'prescriptionScore': none2zero(p[3]),
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
            'cr': cr,
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
def getPrescriptionsStatus():
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    idSegment = request.args.get('idSegment', None)
    idDept = request.args.getlist('idDept[]')
    idDrug = request.args.getlist('idDrug[]')
    limit = request.args.get('limit', 250)
    day = request.args.get('date', date.today())

    patients = Patient.getPatients(idSegment=idSegment, idDept=idDept, idDrug=idDrug, day=day, limit=limit, onlyStatus=True)
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


def getExams(typeExam, admissionNumber):
    return db.session.query(Exams.value, Exams.unit, Exams.date)\
        .select_from(Exams)\
        .filter(Exams.admissionNumber == admissionNumber)\
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

def getDrugType(drugList, pDrugs, source, interventions, exams=None, checked=False, suspended=False, route=False):
    for pd in drugList:

        belong = False

        if pd[0].source is None: pd[0].source = 'Medicamentos'
        if pd[0].source != source: continue
        if source == 'Soluções': belong = True
        if checked and bool(pd[0].checked) == True and bool(pd[0].suspendedDate) == False: belong = True
        if suspended and (bool(pd[0].suspendedDate) == True): belong = True
        if (not checked and not suspended) and (bool(pd[0].checked) == False and bool(pd[0].suspendedDate) == False): belong = True

        pdFrequency = 1 if pd[0].frequency in [33,44,99] else pd[0].frequency

        alerts = []
        doseWeight = None
        if exams and pd[6]:
            if pd[6].maxDose and pd[6].maxDose < (pd[0].doseconv * pdFrequency):
                alerts.append('Dose diária prescrita (' + str(int(pd[0].doseconv * pdFrequency)) + ') maior que a dose de alerta (' + str(pd[6].maxDose) + ') usualmente recomendada (considerada a dose diária máxima independente da indicação.')

            if pd[6].kidney and exams['ckd']['value'] and pd[6].kidney > exams['ckd']['value']:
                alerts.append('Medicamento deve sofrer ajuste de posologia, já que a função renal do paciente (' + str(exams['ckd']['value']) + ' mL/min) está abaixo de ' + str(pd[6].kidney) + ' mL/min.')

            if pd[6].liver:
                if (exams['tgp']['value'] and float(exams['tgp']['value']) > pd[6].liver) or (exams['tgo']['value'] and float(exams['tgo']['value']) > pd[6].liver):
                    alerts.append('Medicamento com necessidade de ajuste de posologia ou contraindicado, já que para paciente com função hepática do paciente está reduzida (acima de ' + str(pd[6].liver) + ' U/L).')

            if pd[6].elderly and exams['age'] > 60:
                alerts.append('Medicamento potencialmente inapropriado para idosos, independente das comorbidades do paciente.')

            if pd[6].useWeight and exams['weight'] > 0:
                doseWeight = str(round(pd[0].dose / float(exams['weight']),2))
                if pd[2].id: doseWeight += ' ' + pd[2].id

        if pd[0].alergy == 'S':
            alerts.append('Paciente alérgico ao medicamento.')

        if belong:
            pDrugs.append({
                'idPrescriptionDrug': pd[0].id,
                'idDrug': pd[0].idDrug,
                'drug': pd[1].name if pd[1] is not None else 'Medicamento ' + str(pd[0].idDrug),
                'np': pd[6].notdefault if pd[6] is not None else False,
                'am': pd[6].antimicro if pd[6] is not None else False,
                'av': pd[6].mav if pd[6] is not None else False,
                'c': pd[6].controlled if pd[6] is not None else False,
                'doseWeight': doseWeight,
                'dose': pd[0].dose,
                'measureUnit': { 'value': pd[2].id, 'label': pd[2].description } if pd[2] else '',
                'frequency': { 'value': pd[3].id, 'label': pd[3].description } if pd[3] else '',
                'dayFrequency': pd[0].frequency,
                'doseconv': pd[0].doseconv,
                'time': timeValue(pd[0].interval),
                'recommendation': pd[0].notes if pd[0].notes and len(pd[0].notes.strip()) > 0 else None,
                'obs': None,
                'period': str(pd[0].period) + 'D' if pd[0].period else '',
                'periodDates': [],
                'route': pd[0].route,
                'grp_solution': pd[0].solutionGroup,
                'stage': 'ACM' if pd[0].solutionACM == 'S' else strNone(pd[0].solutionPhase) + ' x '+ strNone(pd[0].solutionTime) + ' (' + strNone(pd[0].solutionTotalTime) + ')',
                'infusion': strNone(pd[0].solutionDose) + ' ' + strNone(pd[0].solutionUnit),
                'score': str(pd[5]),
                'source': pd[0].source,
                'checked': bool(pd[0].checked),
                'intervened': None,
                'suspended': bool(pd[0].suspendedDate),
                'status': pd[0].status,
                'near': pd[0].near,
                'prevIntervention': getPrevIntervention(pd[0].idDrug, pd[0].idPrescription, interventions),
                'intervention': getIntervention(pd[0].id, interventions),
                'alerts': alerts,
                'notes': pd[7],
                'prevNotes': pd[8]
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
        patient.idPatient = prescription[0].idPatient
        patient.admissionNumber = prescription[0].admissionNumber

    drugs = PrescriptionDrug.findByPrescription(idPrescription, patient.admissionNumber)
    interventions = Intervention.findAll(admissionNumber=patient.admissionNumber)
    db.engine.dispose()

    # TODO: Refactor Query
    tgo = getExams('TGO', patient.admissionNumber)
    tgp = getExams('TGP', patient.admissionNumber)
    cr = getExams('CR', patient.admissionNumber)
    k = getExams('K', patient.admissionNumber)
    na = getExams('NA', patient.admissionNumber)
    mg = getExams('MG', patient.admissionNumber)
    rni = getExams('PRO', patient.admissionNumber)
    pcr = getExams('PCRU', patient.admissionNumber)

    exams = {
        'tgo': formatExam(tgo, 'tgo'),
        'tgp': formatExam(tgp, 'tgp'),
        'mdrd': mdrd_calc(cr.value, patient.birthdate, patient.gender, patient.skinColor) if cr is not None else examEmpty,
        'cg': cg_calc(cr.value, patient.birthdate, patient.gender, patient.weight) if cr is not None else examEmpty,
        'ckd': ckd_calc(cr.value, patient.birthdate, patient.gender, patient.skinColor) if cr is not None else examEmpty,
        'creatinina': formatExam(cr, 'cr'),
        'k': formatExam(k, 'k'),
        'na': formatExam(na, 'na'),
        'mg': formatExam(mg, 'mg'),
        'rni': formatExam(rni, 'rni'),
        'pcr': formatExam(pcr, 'pcr'),
        'age': data2age(patient.birthdate.isoformat() if patient.birthdate else date.today().isoformat()),
        'weight': patient.weight,
    }

    pDrugs = []
    pDrugs = getDrugType(drugs, [], 'Medicamentos', interventions, exams=exams)
    pDrugs = getDrugType(drugs, pDrugs, 'Medicamentos', interventions, checked=True, exams=exams)
    pDrugs = getDrugType(drugs, pDrugs, 'Medicamentos', interventions, suspended=True, exams=exams)
    pDrugs = sortRoute(pDrugs)

    pSolution = []
    pSolution = getDrugType(drugs, [], 'Soluções', interventions)
    #pSolution = getDrugType(drugs, pSolution, checked=True, source='Soluções', interventions=interventions)
    #pSolution = getDrugType(drugs, pSolution, suspended=True, source='Soluções', interventions=interventions)

    pProcedures = []
    pProcedures = getDrugType(drugs, [], 'Proced/Exames', interventions)
    pProcedures = getDrugType(drugs, pProcedures, 'Proced/Exames', interventions, checked=True)
    pProcedures = getDrugType(drugs, pProcedures, 'Proced/Exames', interventions, suspended=True)

    return {
        'status': 'success',
        'data': dict(exams, **{
            'idPrescription': prescription[0].id,
            'idSegment': prescription[0].idSegment,
            'segmentName': prescription[5],
            'idPatient': patient.idPatient,
            'name': prescription[0].admissionNumber,
            'admissionNumber': prescription[0].admissionNumber,
            'birthdate': patient.birthdate.isoformat() if patient.birthdate else '',
            'gender': patient.gender,
            'weight': patient.weight,
            'weightDate': patient.weightDate,
            'bed': prescription[0].bed,
            'record': prescription[0].record,
            'class': random.choice(['green','yellow','red']),
            'skinColor': patient.skinColor,
            'department': prescription[4],
            'patientScore': 'High',
            'date': prescription[0].date.isoformat(),
            'daysAgo': prescription[2],
            'prescriptionScore': str(prescription[3]),
            'prescription': pDrugs,
            'solution': pSolution,
            'procedures': pProcedures,
            'interventions': [i for i in interventions if i['idPrescription'] < idPrescription],
            'status': prescription[0].status,
        })
    }, status.HTTP_200_OK

@app_pres.route('/prescriptions/<int:idPrescription>', methods=['PUT'])
@jwt_required
def setPrescriptionStatus(idPrescription):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    data = request.get_json()

    p = Prescription.query.get(idPrescription)
    p.status = data.get('status', None)
    p.update = datetime.today()
    p.user = user.id

    ppic = PrescriptionPic.query.get(p.id)
    if ppic is None:
        pObj, code = getPrescriptions(idPrescription=p.id)
        ppic = PrescriptionPic()
        ppic.id = p.id
        ppic.picture = pObj['data'][0]
        db.session.add(ppic)

    return tryCommit(db, idPrescription)

@app_pres.route("/prescriptions/drug/<int:idPrescriptionDrug>/period", methods=['GET'])
@jwt_required
def getDrugPeriod(idPrescriptionDrug):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    results = PrescriptionDrug.findByPrescriptionDrug(idPrescriptionDrug)
    db.engine.dispose()

    return {
        'status': 'success',
        'data': results[0][1]
    }, status.HTTP_200_OK

def historyExam(typeExam, examsList):
    results = []
    for e in examsList:
        if e.typeExam == typeExam:
            item = formatExam(e, e.typeExam.lower())
            del(item['ref'])
            results.append(item)
    return results

@app_pres.route("/exams/<int:admissionNumber>", methods=['GET'])
@jwt_required
def getExamsbyAdmission(admissionNumber):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    examsList = Exams.findByAdmission(admissionNumber)
    db.engine.dispose()

    perc = {
        'h_conleuc': {
            'total' : 1,
            'relation': ['h_conlinfoc', 'h_conmono', 'h_coneos', 'h_conbaso', 'h_consegm']
        }
    }

    bufferList = {}
    typeExams = []
    for e in examsList:
        if not e.typeExam in typeExams and e.typeExam.lower() in examsName:
            key = e.typeExam.lower()
            item = formatExam(e, e.typeExam.lower())
            item['name'] = examsName[e.typeExam.lower()]
            item['perc'] = None
            item['history'] = historyExam(e.typeExam, examsList)
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

    results = copy.deepcopy(examsName)
    for e in examsName:
        if e in bufferList:
            results[e] = bufferList[e]
        else:
            del(results[e])

    return {
        'status': 'success',
        'data': results
    }, status.HTTP_200_OK


@app_pres.route('/patient/<int:admissionNumber>', methods=['POST'])
@jwt_required
def setPatientData(admissionNumber):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)
    data = request.get_json()

    p = Patient.findByAdmission(admissionNumber)

    if 'weight' in data.keys(): 
        p.weight = data.get('weight')
        p.weightDate = datetime.today()

    returnJson = tryCommit(db, admissionNumber)

    if 'idPrescription' in data.keys():
        idPrescription = data.get('idPrescription')

        query = "INSERT INTO " + user.schema + ".presmed \
                    SELECT *\
                    FROM " + user.schema + ".presmed\
                    WHERE fkprescricao = " + str(int(idPrescription)) + ";"

        result = db.engine.execute(query)
        print('Update Presmed:', result.rowcount)  

    return returnJson

@app_pres.route('/prescriptions/drug/<int:idPrescriptionDrug>', methods=['PUT'])
@jwt_required
def setPrescriptionDrugNote(idPrescriptionDrug):
    data = request.get_json()
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

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

        note.idDrug = idDrug
        note.admissionNumber = admissionNumber
        note.notes = notes
        note.update = func.now()
        note.user  = user.id

        if newObs: db.session.add(note)

    return tryCommit(db, idPrescriptionDrug)