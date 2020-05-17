from flask_api import status
from models import db, User, Patient, Prescription, PrescriptionDrug, InterventionReason,\
                    Intervention, Segment, setSchema, Department, Outlier, Drug, PrescriptionAgg,\
                    MeasureUnit, MeasureUnitConvert, OutlierObs
from sqlalchemy import desc, asc, and_, func
from flask import Blueprint, request
from flask_jwt_extended import (create_access_token, create_refresh_token,
                                jwt_required, jwt_refresh_token_required, get_jwt_identity, get_raw_jwt)
from .utils import freqValue

app_out = Blueprint('app_out',__name__)

@app_out.route('/outliers/<int:idSegment>/<int:idDrug>', methods=['GET'])
@jwt_required
def getOutliers(idSegment=1, idDrug=1):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)
    outliers = db.session\
        .query(Outlier, OutlierObs)\
        .outerjoin(OutlierObs, OutlierObs.id == Outlier.id)\
        .filter(Outlier.idSegment == idSegment, Outlier.idDrug == idDrug)\
        .order_by(Outlier.countNum.desc())\
        .all()
    d = Drug.query.get(idDrug)
    db.engine.dispose()

    frequency = request.args.get('f', None)
    dose = request.args.get('d', None)

    units = getUnits(idDrug) # TODO: Refactor
    defaultUnit = 'unlikely big name for a measure unit'
    bUnit = False
    for unit in units[0]['data']:
        if unit['fator'] == 1 and len(unit['idMeasureUnit']) < len(defaultUnit):
            defaultUnit = unit['idMeasureUnit']
            bUnit = True

    if not bUnit: defaultUnit = '';

    newOutlier = True
    results = []
    if d != None:
        for o in outliers:
            if dose is not None and frequency is not None:
                if float(dose) == o[0].dose and float(frequency) == o[0].frequency: newOutlier = False
            results.append({
                'idOutlier': o[0].id,
                'idDrug': o[0].idDrug,
                'countNum': o[0].countNum,
                'dose': o[0].dose,
                'unit': defaultUnit,
                'frequency': freqValue(o[0].frequency),
                'score': o[0].score,
                'manualScore': o[0].manualScore,
                'obs': o[1].notes if o[1] != None else ''
            })

    if dose is not None and frequency is not None and newOutlier:
        o = Outlier()
        o.idDrug = idDrug
        o.idSegment = idSegment
        o.countNum = 1
        o.dose = float(dose)
        o.frequency = freqValue(float(frequency))
        o.score = 4
        o.manualScore = None
        o.update = func.now()
        o.user = user.id

        db.session.add(o)
        db.session.commit()

        results.append({
            'idOutlier': o.id,
            'idDrug': idDrug,
            'countNum': 1,
            'dose': float(dose),
            'unit': defaultUnit,
            'frequency': float(frequency),
            'score': 4,
            'manualScore': None,
            'obs': ''
        })

    return {
        'status': 'success',
        'data': {
            'outliers': results,
            'antimicro': d.antimicro,
            'mav': d.mav,
            'controlled': d.controlled,
            'notdefault': d.notdefault,
            'maxDose': d.maxDose,
            'kidney': d.kidney,
            'liver': d.liver,
            'elderly': d.elderly,
            'idMeasureUnit': d.idMeasureUnit
        }
    }, status.HTTP_200_OK


@app_out.route('/outliers/<int:idOutlier>', methods=['PUT'])
@jwt_required
def setManualOutlier(idOutlier):
    data = request.get_json()

    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    o = Outlier.query.get(idOutlier)
    if 'manualScore' in data:
        manualScore = data.get('manualScore', None)
        o.manualScore = manualScore
        o.update = func.now()
        o.user = user.id

    if 'obs' in data:
        notes = data.get('obs', None)
        obs = OutlierObs.query.get(idOutlier)
        newObs = False

        if obs is None:
            newObs = True
            obs = OutlierObs()
            obs.id = idOutlier
            obs.idSegment = o.idSegment
            obs.idDrug = o.idDrug
            obs.dose = o.dose
            obs.frequency = o.frequency

        obs.notes = notes
        obs.update = func.now()
        obs.user  = user.id

        if newObs: db.session.add(obs)

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
    if 'notdefault' in data.keys(): d.notdefault = data.get('notdefault', 0)
    if 'maxDose' in data.keys(): d.maxDose = data.get('maxDose', None)
    if 'kidney' in data.keys(): d.kidney = data.get('kidney', None)
    if 'liver' in data.keys(): d.liver = data.get('liver', 0)
    if 'elderly' in data.keys(): d.elderly = data.get('elderly', 0)

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