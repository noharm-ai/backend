from flask_api import status
from models.main import *
from models.prescription import *
from sqlalchemy import desc, asc, and_, func
from flask import Blueprint, request
from flask_jwt_extended import (create_access_token, create_refresh_token,
                                jwt_required, jwt_refresh_token_required, get_jwt_identity, get_raw_jwt)
from .utils import freqValue, tryCommit, typeRelations, sortSubstance, strNone
from datetime import datetime

app_out = Blueprint('app_out',__name__)

@app_out.route('/outliers/<int:idSegment>/<int:idDrug>', methods=['GET'])
@jwt_required
def getOutliers(idSegment=1, idDrug=1):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    outliers = db.session\
        .query(Outlier, Notes)\
        .outerjoin(Notes, Notes.idOutlier == Outlier.id)\
        .filter(Outlier.idSegment == idSegment, Outlier.idDrug == idDrug)\
        .order_by(Outlier.countNum.desc(), Outlier.frequency.asc())\
        .all()
    d = db.session\
        .query(Drug, Substance.name)\
        .outerjoin(Substance, Substance.id == Drug.sctid)\
        .filter(Drug.id == idDrug)\
        .one()

    drugAttr = DrugAttributes.query.get((idDrug,idSegment))
    
    relations = []
    if d[0].sctid:
        relations = Relation.findBySctid(d[0].sctid, user.id)

    if drugAttr is None: drugAttr = DrugAttributes()

    frequency = request.args.get('f', None)
    dose = request.args.get('d', None)

    units = getUnits(idDrug, idSegment) # TODO: Refactor
    defaultUnit = 'unlikely big name for a measure unit'
    bUnit = False
    for unit in units[0]['data']:
        if unit['fator'] == 1 and len(unit['idMeasureUnit']) < len(defaultUnit):
            defaultUnit = unit['idMeasureUnit']
            bUnit = True

    if not bUnit: defaultUnit = '';

    newOutlier = True
    results = []
    if d[0] != None:
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
        o.frequency = float(frequency)
        o.score = 4
        o.manualScore = None
        o.update = datetime.today()
        o.user = user.id

        db.session.add(o)
        db.session.flush()

        results.append({
            'idOutlier': o.id,
            'idDrug': idDrug,
            'countNum': 1,
            'dose': float(dose),
            'unit': defaultUnit,
            'frequency': freqValue(float(frequency)),
            'score': 4,
            'manualScore': None,
            'obs': ''
        })

    returnJson = {
        'status': 'success',
        'data': {
            'outliers': results,
            'antimicro': drugAttr.antimicro,
            'mav': drugAttr.mav,
            'controlled': drugAttr.controlled,
            'notdefault': drugAttr.notdefault,
            'maxDose': drugAttr.maxDose,
            'kidney': drugAttr.kidney,
            'liver': drugAttr.liver,
            'elderly': drugAttr.elderly,
            'division': drugAttr.division,
            'useWeight': drugAttr.useWeight,
            'idMeasureUnit': drugAttr.idMeasureUnit or defaultUnit,
            'amount': drugAttr.amount,
            'amountUnit': drugAttr.amountUnit,
            'whiteList': drugAttr.whiteList,
            'sctidA': d[0].sctid,
            'sctNameA': strNone(d[1]).upper(),
            'relations': relations,
            'relationTypes' : [{'key': t, 'value': typeRelations[t]} for t in typeRelations]
        }
    }

    tryCommit(db, idDrug)
    return returnJson, status.HTTP_200_OK


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
        o.update = datetime.today()
        o.user = user.id

    if 'obs' in data:
        notes = data.get('obs', None)
        obs = Notes.query.get((idOutlier,0))
        newObs = False

        if obs is None:
            newObs = True
            obs = Notes()
            obs.idOutlier = idOutlier
            obs.idPrescriptionDrug = 0
            obs.idSegment = o.idSegment
            obs.idDrug = o.idDrug
            obs.dose = o.dose
            obs.frequency = o.frequency

        obs.notes = notes
        obs.update = datetime.today()
        obs.user  = user.id

        if newObs: db.session.add(obs)

    return tryCommit(db, idOutlier)


@app_out.route('/drugs/<int:idDrug>', methods=['PUT'])
@jwt_required
def setDrugClass(idDrug):
    data = request.get_json()
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    idSegment = data.get('idSegment', 1)
    drugAttr = DrugAttributes.query.get((idDrug,idSegment))

    newDrugAttr = False
    if drugAttr is None:
        newDrugAttr = True
        drugAttr = DrugAttributes()
        drugAttr.idDrug = idDrug
        drugAttr.idSegment = idSegment

    if 'antimicro' in data.keys(): drugAttr.antimicro = bool(data.get('antimicro', 0))
    if 'mav' in data.keys(): drugAttr.mav = bool(data.get('mav', 0))
    if 'controlled' in data.keys(): drugAttr.controlled = bool(data.get('controlled', 0))
    if 'idMeasureUnit' in data.keys(): drugAttr.idMeasureUnit = data.get('idMeasureUnit', None)
    if 'notdefault' in data.keys(): drugAttr.notdefault = data.get('notdefault', 0)
    if 'maxDose' in data.keys(): drugAttr.maxDose = data.get('maxDose', None)
    if 'kidney' in data.keys(): drugAttr.kidney = data.get('kidney', None)
    if 'liver' in data.keys(): drugAttr.liver = data.get('liver', None)
    if 'elderly' in data.keys(): drugAttr.elderly = data.get('elderly', 0)
    if 'division' in data.keys(): drugAttr.division = data.get('division', None)
    if 'useWeight' in data.keys(): drugAttr.useWeight = data.get('useWeight', 0)
    if 'amount' in data.keys(): drugAttr.amount = data.get('amount', 0)
    if 'amountUnit' in data.keys(): drugAttr.amountUnit = data.get('amountUnit', None)
    if 'whiteList' in data.keys(): 
        drugAttr.whiteList = data.get('whiteList', None)
        if not drugAttr.whiteList: drugAttr.whiteList = None

    if newDrugAttr: db.session.add(drugAttr)

    return tryCommit(db, idDrug)


@app_out.route('/drugs', methods=['GET'])
@app_out.route('/drugs/<int:idSegment>', methods=['GET'])
@jwt_required
def getDrugs(idSegment=1):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    qDrug = request.args.get('q', None)
    idDrug = request.args.getlist('idDrug[]')

    drugs = Drug.query\
            .join(Outlier, Outlier.idDrug == Drug.id)\
            .filter(Outlier.idSegment == idSegment)

    if qDrug: drugs = drugs.filter(Drug.name.ilike("%"+str(qDrug)+"%"))

    if (len(idDrug)>0): drugs = drugs.filter(Drug.id.in_(idDrug))

    drugs = drugs.order_by(asc(Drug.name)).all()

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
def getUnits(idDrug, idSegment=1):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    idSegment = request.args.get('idSegment', idSegment)

    u = db.aliased(MeasureUnit)
    p = db.aliased(PrescriptionAgg)
    mu = db.aliased(MeasureUnitConvert)
    d = db.aliased(Drug)

    units = db.session.query(u.id, u.description, d.name,
                            func.sum(p.countNum).label('count'), func.max(mu.factor).label('factor'))\
            .select_from(u)\
            .join(p, and_(p.idMeasureUnit == u.id, p.idDrug == idDrug))\
            .join(d, and_(d.id == idDrug))\
            .outerjoin(mu, and_(mu.idMeasureUnit == u.id, mu.idDrug == idDrug, mu.idSegment == p.idSegment))\
            .filter(p.idSegment == idSegment)\
            .group_by(u.id, u.description, p.idMeasureUnit, d.name)\
            .order_by(asc(u.description))\
            .all()

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

    idSegment = data.get('idSegment', 1)
    u = MeasureUnitConvert.query.get((idMeasureUnit, idDrug, idSegment))
    new = False

    if u is None:
        new = True
        u = MeasureUnitConvert()
        u.idMeasureUnit = idMeasureUnit
        u.idDrug = idDrug
        u.idSegment = idSegment

    u.factor = data.get('fator', 1)

    if new: db.session.add(u)

    return tryCommit(db, idMeasureUnit)

@app_out.route('/substance', methods=['GET'])
@jwt_required
def getSubstance():
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    drugs = Substance.query.order_by(asc(Substance.name)).all()

    results = []
    for d in drugs:
        results.append({
            'sctid': d.id,
            'name': d.name.upper(),
        })

    results.sort(key=sortSubstance)

    return {
        'status': 'success',
        'data': results
    }, status.HTTP_200_OK


@app_out.route('/relation/<int:sctidA>/<int:sctidB>/<string:kind>', methods=['PUT'])
@jwt_required
def setRelation(sctidA,sctidB,kind):
    data = request.get_json()
    user = User.find(get_jwt_identity())

    relation = Relation.query.get((sctidA,sctidB,kind))
    if relation is None:
        relation = Relation.query.get((sctidB,sctidA,kind))

    newRelation = False
    if relation is None:
        newRelation = True
        relation = Relation()
        relation.sctida = sctidA
        relation.sctidb = sctidB
        relation.kind = kind
        relation.creator  = user.id

    if 'text' in data.keys(): relation.text = data.get('text', None)
    if 'active' in data.keys(): relation.active = bool(data.get('active', False))

    relation.update = datetime.today()
    relation.user  = user.id

    if newRelation: db.session.add(relation)

    return tryCommit(db, sctidA)