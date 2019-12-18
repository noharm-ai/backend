from flask_api import status
from models import db, User, Patient, Prescription, PrescriptionDrug, InterventionReason, Intervention, Segment, setSchema, Exams
from flask import Blueprint, request
from flask_jwt_extended import (create_access_token, create_refresh_token,
                                jwt_required, jwt_refresh_token_required, get_jwt_identity, get_raw_jwt)

app_pres = Blueprint('app_pres',__name__)

@app_pres.route("/patients", methods=['GET'])
@app_pres.route("/prescriptions", methods=['GET'])
@jwt_required
def getPrescriptions():
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    patients = Patient.getPatients(
        name=request.args.get('name'), order=request.args.get('order'),
        direction=request.args.get('direction'), limit=request.args.get('limit'),
        idSegment=request.args.get('idSegment')
    )
    db.engine.dispose()

    results = []
    for p in patients:
        results.append({
            'idPrescription': p[0].id,
            'idPatient': p[0].idPatient,
            'name': p[1].admissionNumber,
            'birthdate': p[1].birthdate.isoformat(),
            'gender': p[1].gender,
            'weight': p[1].weight,
            'race': p[1].race,
            'date': p[0].date.isoformat(),
            'daysAgo': p[2],
            'prescriptionScore': str(p[3]),
            'scoreOne': str(p[4]),
            'scoreTwo': str(p[5]),
            'scoreThree': str(p[6]),
            'tgo': str(p[7]),
            'tgp': str(p[8]),
            'mdrd': str(p[9]),
            'patientScore': 'High',
        })
        print(p)

    return {
        'status': 'success',
        'data': results
    }, status.HTTP_200_OK


def getExams(typeExam, idPatient):
    return db.session.query(Exams.value, Exams.unit)\
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

    drugs = PrescriptionDrug.findByPrescription(idPrescription)
    db.engine.dispose()

    tgo = getExams('TGO', prescription[1].id)
    tgp = getExams('TGP', prescription[1].id)
    cr = getExams('CR', prescription[1].id)

    pDrugs = []
    for pd in drugs:
        pDrugs.append({
            'idPrescriptionDrug': pd[0].id,
            'idDrug': pd[0].idDrug,
            'drug': pd[1].name,
            'dose': pd[0].dose,
            'measureUnit': pd[2].description,
            'frequency': pd[3].description,
            'route': pd[0].route,
            'score': str(pd[5]),
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
            'idPatient': prescription[1].id,
            'name': prescription[1].admissionNumber,
            'admissionNumber': prescription[1].admissionNumber,
            'birthdate': prescription[1].birthdate.isoformat(),
            'gender': prescription[1].gender,
            'weight': prescription[1].weight,
            'race': prescription[1].race,
            'tgo': str(tgo.value) + ' ' + tgo.unit if tgo is not None else '',
            'tgp': str(tgp.value) + ' ' + tgp.unit if tgp is not None else '',
            'mdrd': str(cr.value) + ' ' + cr.unit if cr is not None else '',
            'creatinina': str(cr.value) + ' ' + cr.unit if cr is not None else '',
            'patientScore': 'High',
            'date': prescription[0].date.isoformat(),
            'daysAgo': prescription[2],
            'prescriptionScore': str(prescription[3]),
            'prescription': pDrugs
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