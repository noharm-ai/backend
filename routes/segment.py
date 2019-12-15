from __main__ import app
from flask_api import status
from models import db, User, Patient, Prescription, PrescriptionDrug, InterventionReason, Intervention, Segment, setSchema
from flask import request
from flask_jwt_extended import (create_access_token, create_refresh_token,
                                jwt_required, jwt_refresh_token_required, get_jwt_identity, get_raw_jwt)


@app.route("/segments", methods=['GET'])
@jwt_required
def getSegments():
    user = User.find(get_jwt_identity())
    setSchema(user.schema)
    results = Segment.findAll()
    db.engine.dispose()

    iList = []
    for i in results:
        iList.append({
            'id': i.id,
            'description': i.description,
            'minAge': i.minAge,
            'maxAge': i.maxAge,
            'minWeight': i.minWeight,
            'maxWeight': i.maxWeight,
            'status': i.status
        })

    return {
        'status': 'success',
        'data': iList
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
