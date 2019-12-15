from __main__ import app
from flask_api import status
from models import db, User, Patient, Prescription, PrescriptionDrug, InterventionReason, Intervention, Segment, setSchema
from flask import request
from flask_jwt_extended import (create_access_token, create_refresh_token,
                                jwt_required, jwt_refresh_token_required, get_jwt_identity, get_raw_jwt)


@app.route("/patients", methods=['GET'])
@app.route("/prescriptions", methods=['GET'])
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
            'prescriptionScore': str(p[3])
        })

    return {
        'status': 'success',
        'data': results
    }, status.HTTP_200_OK


@app.route('/prescriptions/<int:idPrescription>', methods=['GET'])
@jwt_required
def getPrescription(idPrescription):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)
    prescription = Prescription.getPrescription(idPrescription)

    if (prescription is None):
        return {}, status.HTTP_204_NO_CONTENT

    drugs = PrescriptionDrug.findByPrescription(idPrescription)
    db.engine.dispose()

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
            'score': str(pd[4])
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
            'date': prescription[0].date.isoformat(),
            'daysAgo': prescription[2],
            'prescriptionScore': str(prescription[3]),
            'prescription': pDrugs
        }
    }, status.HTTP_200_OK


@app.route("/intervention/reasons", methods=['GET'])
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


@app.route('/intervention', methods=['POST'])
@app.route('/intervention/<int:idIntervention>', methods=['PUT'])
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
