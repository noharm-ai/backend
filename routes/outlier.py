from __main__ import app
from flask_api import status
from models import db, User, Patient, Prescription, PrescriptionDrug, InterventionReason, Intervention, Segment, setSchema, Department, Outlier
from flask import request
from flask_jwt_extended import (create_access_token, create_refresh_token,
                                jwt_required, jwt_refresh_token_required, get_jwt_identity, get_raw_jwt)


@app.route('/outliers/<int:idSegment>/<int:idDrug>', methods=['GET'])
@jwt_required
def getOutliers(idSegment=1, idDrug=1):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)
    outliers = Outlier.query\
        .filter(Outlier.idSegment == idSegment, Outlier.idDrug == idDrug)\
        .all()
    db.engine.dispose()

    results = []
    for o in outliers:
        results.append({
            'idOutlier': o.id,
            'idDrug': o.idDrug,
            'countNum': o.countNum,
            'dose': o.dose,
            'frequency': o.frequency,
            'score': o.score,
            'manualScore': o.manualScore,
        })

    return {
        'status': 'success',
        'data': results
    }, status.HTTP_200_OK


@app.route('/outliers/<int:idOutlier>', methods=['PUT'])
@jwt_required
def setManualOutlier(idOutlier):
    data = request.get_json()

    user = User.find(get_jwt_identity())
    setSchema(user.schema)
    o = Outlier.query.get(idOutlier)
    o.idUser = 1
    o.manualScore = data.get('manualScore', None)

    try:
        db.session.commit()

        return {
            'status': 'success',
            'data': o.id
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


@app.route('/drugs', methods=['GET'])
@jwt_required
def getDrugs():
    user = User.find(get_jwt_identity())
    setSchema(user.schema)
    drugs = Drug.query.all()
    db.engine.dispose()

    results = []
    for d in drugs:
        results.append({
            'idDrug': d.id,
            'name': d.name,
        })

    return {
        'status': 'success',
        'data': results
    }, status.HTTP_200_OK


@app.route('/departments', methods=['GET'])
@jwt_required
def getDepartments():
    user = User.find(get_jwt_identity())
    setSchema(user.schema)
    departs = Department.query.all()
    db.engine.dispose()

    results = []
    for d in departs:
        results.append({
            'idDepartment': d.id,
            'idHospital': d.idHospital,
            'name': d.name,
        })

    return {
        'status': 'success',
        'data': results
    }, status.HTTP_200_OK


@app.route('/segments', methods=['POST'])
@app.route('/segments/<int:idSegment>', methods=['PUT'])
@jwt_required
def setSegment(idSegment=None):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    if request.method == 'POST':
        s = Segment()
    elif request.method == 'PUT':
        s = Segment.query.get(idSegment)

    data = request.get_json()
    if 'description' in data:
        s.description = data.get('description', None)
    if 'minAge' in data:
        s.minAge = data.get('minAge', None)
    if 'maxAge' in data:
        s.maxAge = data.get('maxAge', None)
    if 'minWeight' in data:
        s.minWeight = data.get('minWeight', None)
    if 'maxWeight' in data:
        s.maxWeight = data.get('maxWeight', None)
    if 'status' in data:
        s.status = data.get('status', None)

    if request.method == 'POST':
        db.session.add(s)

    try:
        db.session.commit()

        return {
            'status': 'success',
            'data': s.id
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
