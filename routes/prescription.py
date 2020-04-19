import random
from flask_api import status
from models import db, User, Patient, Prescription, PrescriptionDrug, InterventionReason, Intervention, Segment, setSchema, Exams, PrescriptionPic
from flask import Blueprint, request
from flask_jwt_extended import (create_access_token, create_refresh_token,
                                jwt_required, jwt_refresh_token_required, get_jwt_identity, get_raw_jwt)
from .utils import mdrd_calc, cg_calc, none2zero, formatExam
from sqlalchemy import func
from datetime import date

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
    limit = request.args.get('limit', 200)

    patients = Patient.getPatients(idSegment=idSegment, idDept=idDept, idPrescription=idPrescription, limit=200)
    db.engine.dispose()

    results = []
    for p in patients:

        patient = p[1]
        if (patient is None):
            patient = Patient()
            patient.birthdate = date.today()
            patient.id = p[0].idPatient
            patient. admissionNumber = p[0].admissionNumber

        results.append({
            'idPrescription': p[0].id,
            'idPatient': p[0].idPatient,
            'name': patient.admissionNumber,
            'admissionNumber': patient.admissionNumber,
            'birthdate': patient.birthdate.isoformat(),
            'gender': patient.gender,
            'weight': patient.weight,
            'skinColor': patient.skinColor,
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
            'tgo': none2zero(p[7]),
            'tgp': none2zero(p[8]),
            'mdrd': mdrd_calc(str(p[9]), patient.birthdate.isoformat(), patient.gender, patient.skinColor),
            'cg': cg_calc(str(p[9]), patient.birthdate.isoformat(), patient.gender, patient.weight),
            'k': none2zero(p[10]),
            'na': none2zero(p[11]),
            'mg': none2zero(p[12]),
            'rni': none2zero(p[13]),
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
    limit = request.args.get('limit', 200)

    patients = Patient.getPatients(idSegment=idSegment, limit=limit, idDept=idDept, onlyStatus=True)
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

def getDrugType(drugList, pDrugs, checked=False, suspended=False, source=None):
    for pd in drugList:

        belong = False

        if not source is None and pd[0].source != source: continue
        if checked and (str(pd[6]) == '1' and bool(pd[0].suspendedDate) == False): belong = True
        if suspended and (bool(pd[0].suspendedDate) == True): belong = True
        if (not checked and not suspended) and (str(pd[6]) == '0' and bool(pd[0].suspendedDate) == False): belong = True

        if belong:
            pDrugs.append({
                'idPrescriptionDrug': pd[0].id,
                'idDrug': pd[0].idDrug,
                'drug': pd[1].name if pd[1] is not None else 'Medicamento ' + str(pd[0].idDrug),
                'dose': pd[0].dose,
                'measureUnit': pd[2].description,
                'frequency': pd[3].description,
                'time': pd[0].interval,
                'recommendation': pd[0].notes,
                'obs': pd[8],
                'period': str(len(pd[9])) + 'D',
                'periodDates': [d.isoformat() for d in pd[9]],
                'route': pd[0].route,
                'score': str(pd[5]),
                'source': pd[0].source,
                'checked': bool(pd[6]),
                'intervened': bool(pd[7]),
                'suspended': bool(pd[0].suspendedDate),
                'status': pd[0].status,
                'near': pd[0].near,
                'intervention': {
                    'id': pd[4].id,
                    'idPrescriptionDrug': pd[4].idPrescriptionDrug,
                    'idInterventionReason': pd[4].idInterventionReason,
                    'propagation': pd[4].propagation,
                    'observation': pd[4].notes,
                } if pd[4] is not None else ''
            })
    return pDrugs

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
        patient.birthdate = date.today()
        patient.id = prescription[0].idPatient
        patient.admissionNumber = prescription[0].admissionNumber

    drugs = PrescriptionDrug.findByPrescription(idPrescription, patient.admissionNumber)
    db.engine.dispose()

    tgo = getExams('TGO', patient.id)
    tgp = getExams('TGP', patient.id)
    cr = getExams('CR', patient.id)
    k = getExams('K', patient.id)
    na = getExams('NA', patient.id)
    mg = getExams('MG', patient.id)
    rni = getExams('PRO', patient.id)

    pDrugs = getDrugType(drugs, [])
    pDrugs = getDrugType(drugs, pDrugs, checked=True)
    pDrugs = getDrugType(drugs, pDrugs, suspended=True)

    pSolution = getDrugType(drugs, [], source='Solucoes')
    pSolution = getDrugType(drugs, pSolution, checked=True, source='Solução')
    pSolution = getDrugType(drugs, pSolution, suspended=True, source='Solução')

    pProcedures = getDrugType(drugs, [], source='Proced/Exames')
    pProcedures = getDrugType(drugs, pProcedures, checked=True, source='Proced/Exames')
    pProcedures = getDrugType(drugs, pProcedures, suspended=True, source='Proced/Exames')

    return {
        'status': 'success',
        'data': {
            'idPrescription': prescription[0].id,
            'idSegment': prescription[0].idSegment,
            'idPatient': patient.id,
            'name': prescription[0].admissionNumber,
            'admissionNumber': prescription[0].admissionNumber,
            'birthdate': patient.birthdate.isoformat(),
            'gender': patient.gender,
            'weight': patient.weight,
            'weightDate': patient.weightDate.isoformat() if patient.weightDate else '',
            'class': random.choice(['green','yellow','red']),
            'skinColor': patient.skinColor,
            'department': prescription[4],
            'tgo': formatExam(tgo),
            'tgp': formatExam(tgp),
            'mdrd': {'value': mdrd_calc(cr.value, patient.birthdate.isoformat(), patient.gender, patient.skinColor)} if cr is not None else '',
            'cg': {'value': cg_calc(cr.value, patient.birthdate.isoformat(), patient.gender, patient.weight)} if cr is not None else '',
            'creatinina': formatExam(cr),
            'k': formatExam(k),
            'na': formatExam(na),
            'mg': formatExam(mg),
            'rni': formatExam(rni),
            'patientScore': 'High',
            'date': prescription[0].date.isoformat(),
            'daysAgo': prescription[2],
            'prescriptionScore': str(prescription[3]),
            'prescription': pDrugs,
            'solution': pSolution,
            'procedures': pProcedures,
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


@app_pres.route('/intervention', methods=['POST'])
@app_pres.route('/intervention/<int:idIntervention>', methods=['PUT'])
@jwt_required
def createIntervention(idIntervention=None):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)
    data = request.get_json()

    if request.method == 'POST':
        i = Intervention()
    elif request.method == 'PUT':
        i = Intervention.query.get(idIntervention)

    i.id = idIntervention
    i.idUser = user.id
    i.idPrescriptionDrug = data.get('idPrescriptionDrug', None)
    i.idInterventionReason = data.get('idInterventionReason', None)
    i.propagation = data.get('propagation', None)
    i.notes = data.get('observation', None)

    try:
        i.save()
        db.engine.dispose()

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
        p, code = getPrescriptions(idSegment=p.idSegment, idPrescription=p.id)
        ppic = PrescriptionPic()
        ppic.id = p.id
        ppic.picture = p['data'][0]
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

@app_pres.route('/prescriptions/drug/<int:idPrescriptionDrug>', methods=['PUT'])
@jwt_required
def setDrugStatus(idPrescriptionDrug):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    data = request.get_json()

    pd = PrescriptionDrug.query.get(idPrescriptionDrug)
    pd.status = data.get('status', None)
    pd.update = func.now()
    pd.user = user.id

    ppic = PrescriptionPic.query.get(pd.idPrescription)
    if ppic is None:
        p, code = getPrescriptions(idSegment=pd.idSegment, idPrescription=pd.idPrescription)
        ppic = PrescriptionPic()
        ppic.id = pd.idPrescription
        ppic.picture = p['data'][0]
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