from flask_api import status
from models import db, User, Patient, Prescription, PrescriptionDrug, InterventionReason,\
                    Intervention, Segment, setSchema, Department, Outlier, Drug, PrescriptionAgg,\
                    MeasureUnit, MeasureUnitConvert
from sqlalchemy import desc, asc, and_, func
from flask import Blueprint, request
from flask_jwt_extended import (create_access_token, create_refresh_token,
                                jwt_required, jwt_refresh_token_required, get_jwt_identity, get_raw_jwt)

app_out = Blueprint('app_out',__name__)

@app_out.route('/outliers/<int:idSegment>/<int:idDrug>', methods=['GET'])
@jwt_required
def getOutliers(idSegment=1, idDrug=1):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)
    outliers = Outlier.query\
        .filter(Outlier.idSegment == idSegment, Outlier.idDrug == idDrug)\
        .order_by(Outlier.countNum.desc())\
        .all()
    d = Drug.query.get(idDrug)

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
            'antimicro': d.antimicro,
            'mav': d.mav,
            'controlled': d.controlled,
            'idMeasureUnit': d.idMeasureUnit
        })

    return {
        'status': 'success',
        'data': results
    }, status.HTTP_200_OK


@app_out.route('/outliers/<int:idOutlier>', methods=['PUT'])
@jwt_required
def setManualOutlier(idOutlier):
    data = request.get_json()

    user = User.find(get_jwt_identity())
    setSchema(user.schema)
    o = Outlier.query.get(idOutlier)
    o.idUser = user.id
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


@app_out.route('/drugs/<int:idDrug>', methods=['PUT'])
@jwt_required
def setDrugClass(idDrug):
    data = request.get_json()

    user = User.find(get_jwt_identity())
    setSchema(user.schema)
    d = Drug.query.get(idDrug)

    if 'antimicro' in data.keys(): d.antimicro = bool(data.get('antimicro', 0))
    if 'mav' in data.keys(): d.mav = bool(data.get('mav', 0))
    if 'controlled' in data.keys(): d.controlled = bool(data.get('controlled', 0))
    if 'idMeasureUnit' in data.keys(): d.idMeasureUnit = data.get('idMeasureUnit', None)

    try:
        db.session.commit()

        return {
            'status': 'success',
            'data': d.id
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

@app_out.route('/drugs', methods=['GET'])
@app_out.route('/drugs/<int:idSegment>', methods=['GET'])
@jwt_required
def getDrugs(idSegment=1):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    drugs = Drug.query\
            .join(Outlier, Outlier.idDrug == Drug.id)\
            .filter(Outlier.idSegment == idSegment)\
            .order_by(asc(Drug.name))\
            .all()

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

@app_out.route('/drugs/<int:idDrug>/units', methods=['GET'])
@jwt_required
def getUnits(idDrug):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    u = db.aliased(MeasureUnit)
    p = db.aliased(PrescriptionAgg)
    mu = db.aliased(MeasureUnitConvert)
    d = db.aliased(Drug)

    units = db.session.query(u.id, u.description, d.name,
                            func.sum(p.countNum).label('count'), func.max(mu.factor).label('factor'))\
            .select_from(u)\
            .join(p, and_(p.idMeasureUnit == u.id, p.idDrug == idDrug, p.idSegment == 1))\
            .join(d, and_(d.id == idDrug))\
            .outerjoin(mu, and_(mu.idMeasureUnit == u.id, mu.idDrug == idDrug))\
            .group_by(u.id, u.description, p.idMeasureUnit, d.name)\
            .order_by(asc(u.description))\
            .all()

    db.engine.dispose()

    results = []
    for u in units:
        print(u)
        results.append({
            'idMeasureUnit': u.id,
            'description': u.description,
            'drugName': u[2],
            'fator': u[4] if u[4] != None else 1,
            'contagem': u[3]
        })

    return {
        'status': 'success',
        'data': results
    }, status.HTTP_200_OK

@app_out.route('/drugs/<int:idDrug>/convertunit/<string:idMeasureUnit>', methods=['POST'])
@jwt_required
def setDrugUnit(idDrug, idMeasureUnit):
    data = request.get_json()

    user = User.find(get_jwt_identity())
    setSchema(user.schema)
    u = MeasureUnitConvert.query.get((idMeasureUnit, idDrug))
    new = False

    print('DEBUG: ', u)

    if u is None:
        new = True
        u = MeasureUnitConvert()
        u.idMeasureUnit = idMeasureUnit
        u.idDrug = idDrug
        u.idHospital = 1

    u.factor = data.get('fator', 1)

    if new: db.session.add(u)

    try:
        db.session.commit()

        return {
            'status': 'success',
            'data': u.idMeasureUnit
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