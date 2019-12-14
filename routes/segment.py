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
