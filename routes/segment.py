from flask_api import status
from models import db, User, Patient, Prescription, PrescriptionDrug, InterventionReason, Intervention, Segment, setSchema, SegmentDepartment, Department
from flask import Blueprint, request
from flask_jwt_extended import (create_access_token, create_refresh_token,
                                jwt_required, jwt_refresh_token_required, get_jwt_identity, get_raw_jwt)

app_seg = Blueprint('app_seg',__name__)

@app_seg.route("/segments", methods=['GET'])
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

@app_seg.route("/segments/<int:idSegment>", methods=['GET'])
@jwt_required
def getSegmentsId(idSegment):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)
    
    s = Segment.query.get(idSegment)
    departments = SegmentDepartment.query\
        .filter(SegmentDepartment.id == idSegment)\
        .all()

    deps = []
    for d in departments:
        deps.append({
            'idHospital': d.idHospital,
            'idDepartment': d.idDepartment,
            'name': d.name,
        })

    return {
        'status': 'success',
        'data': {
            'id': s.id,
            'description': s.description,
            'minAge': s.minAge,
            'maxAge': s.maxAge,
            'minWeight': s.minWeight,
            'maxWeight': s.maxWeight,
            'status': s.status,
            'departments': deps
        }
    }, status.HTTP_200_OK

@app_seg.route('/segments', methods=['POST'])
@app_seg.route('/segments/<int:idSegment>', methods=['PUT'])
@jwt_required
def setSegment(idSegment=None):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    if request.method == 'POST':
        s = Segment()
    elif request.method == 'PUT':
        s = Segment.query.get(idSegment)

    db.session.query(SegmentDepartment).filter(SegmentDepartment.id == idSegment).delete()

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
        db.session.commit()

    idSegment = s.id
    deps = data.get('departments', None)
    for d in deps:
        sd = SegmentDepartment()
        sd.id = idSegment
        sd.idHospital = d.get('idHospital', None)
        sd.idDepartment = d.get('idDepartment', None)
        db.session.add(sd)

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

@app_seg.route('/departments', methods=['GET'])
@jwt_required
def getDepartments():
    user = User.find(get_jwt_identity())
    setSchema(user.schema)
    
    departs = Department.getAll()
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

@app_seg.route('/departments/free', methods=['GET'])
@jwt_required
def getFreeDepartments():
    user = User.find(get_jwt_identity())
    setSchema(user.schema)
    
    departs = Department.query\
                .outerjoin(SegmentDepartment, SegmentDepartment.idDepartment == Department.id)\
                .filter(SegmentDepartment.id == None)\
                .all()
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