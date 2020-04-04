import random
from flask_api import status
from models import db, User, Patient, Prescription, PrescriptionDrug, InterventionReason, Intervention, Segment, setSchema, Exams
from flask import Blueprint, request
from flask_jwt_extended import (create_access_token, create_refresh_token,
                                jwt_required, jwt_refresh_token_required, get_jwt_identity, get_raw_jwt)
from .utils import mdrd_calc, cg_calc, none2zero, formatExam
from sqlalchemy import func

app_pres = Blueprint('app_pres',__name__)

@app_pres.route("/patients", methods=['GET'])
@app_pres.route("/prescriptions", methods=['GET'])
@app_pres.route("/prescriptions/segments/<int:idSegment>", methods=['GET'])
@jwt_required
def getPrescriptions(idSegment=1):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    patients = Patient.getPatients(idSegment=idSegment, limit=200)
    db.engine.dispose()

    results = []
    for p in patients:
        results.append({
            'idPrescription': p[0].id,
            'idPatient': p[0].idPatient,
            'name': p[1].admissionNumber,
            'admissionNumber': p[1].admissionNumber,
            'birthdate': p[1].birthdate.isoformat(),
            'gender': p[1].gender,
            'weight': p[1].weight,
            'skinColor': p[1].skinColor,
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
            'tube': str(p[17]),
            'diff': str(p[18]),
            'tgo': none2zero(p[7]),
            'tgp': none2zero(p[8]),
            'mdrd': mdrd_calc(str(p[9]), p[1].birthdate.isoformat(), p[1].gender, p[1].skinColor),
            'cg': cg_calc(str(p[9]), p[1].birthdate.isoformat(), p[1].gender, p[1].weight),
            'k': none2zero(p[10]),
            'na': none2zero(p[11]),
            'mg': none2zero(p[12]),
            'rni': none2zero(p[13]),
            'patientScore': 'Alto',
            'class': 'yellow', #random.choice(['green','yellow','red']),
            'status': p[0].status,
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

@app_pres.route('/prescriptions/<int:idPrescription>', methods=['GET'])
@jwt_required
def getPrescription(idPrescription):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    prescription = Prescription.getPrescription(idPrescription)

    if (prescription is None):
        return {}, status.HTTP_204_NO_CONTENT

    drugs = PrescriptionDrug.findByPrescription(idPrescription, prescription[1].id)
    db.engine.dispose()

    tgo = getExams('TGO', prescription[1].id)
    tgp = getExams('TGP', prescription[1].id)
    cr = getExams('CR', prescription[1].id)
    k = getExams('K', prescription[1].id)
    na = getExams('NA', prescription[1].id)
    mg = getExams('MG', prescription[1].id)
    rni = getExams('PRO', prescription[1].id)

    pDrugs = []
    for pd in drugs:
        pDrugs.append({
            'idPrescriptionDrug': pd[0].id,
            'idDrug': pd[0].idDrug,
            'drug': pd[1].name if pd[1] is not None else 'Medicamento ' + str(pd[0].idDrug),
            'dose': pd[0].dose,
            'measureUnit': pd[2].description,
            'frequency': pd[3].description,
            'route': pd[0].route,
            'score': str(pd[5]),
            'checked': str(pd[6]),
            'status': pd[0].status,
            'intervention': {
                'id': pd[4].id,
                'idPrescriptionDrug': pd[4].idPrescriptionDrug,
                'idInterventionReason': pd[4].idInterventionReason,
                'propagation': pd[4].propagation,
                'observation': pd[4].observation,
            } if pd[4] is not None else ''
        })

    return {
        'status': 'success',
        'data': {
            'idPrescription': prescription[0].id,
            'idSegment': prescription[0].idSegment,
            'idPatient': prescription[1].id,
            'name': prescription[1].admissionNumber,
            'admissionNumber': prescription[1].admissionNumber,
            'birthdate': prescription[1].birthdate.isoformat(),
            'gender': prescription[1].gender,
            'weight': prescription[1].weight,
            'class': random.choice(['green','yellow','red']),
            'skinColor': prescription[1].skinColor,
            'department': prescription[4],
            'tgo': formatExam(tgo),
            'tgp': formatExam(tgp),
            'mdrd': mdrd_calc(cr.value, prescription[1].birthdate.isoformat(), prescription[1].gender, prescription[1].skinColor) if cr is not None else '',
            'cg': cg_calc(cr.value, prescription[1].birthdate.isoformat(), prescription[1].gender, prescription[1].weight) if cr is not None else '',
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
    i.observation = data.get('observation', None)

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