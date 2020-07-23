from models.main import *
from models.prescription import *
from flask import Blueprint, request
from flask_jwt_extended import (jwt_required, get_jwt_identity)

app_sub = Blueprint('app_sub',__name__)

@app_sub.route('/substance', methods=['GET'])
@jwt_required
def getSubstance():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

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

@app_sub.route('/substance/<int:idSubstance>', methods=['PUT'])
@jwt_required
def setSubstance(idSubstance):
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    subs = Substance.query.get(idSubstance)

    newSubs = False
    if subs is None:
        newSubs = True
        subs = Substance()
        subs.id = idSubstance

    subs.name = data.get('name', None)

    if newSubs: db.session.add(subs)

    return tryCommit(db, idSubstance)

@app_sub.route('/substance/<int:idSubstance>/relation', methods=['GET'])
@jwt_required
def getRelations(idSubstance):
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    relations = Relation.findBySctid(idSubstance, user.id)

    return {
        'status': 'success',
        'data': relations
    }, status.HTTP_200_OK

@app_sub.route('/relation/<int:sctidA>/<int:sctidB>/<string:kind>', methods=['PUT'])
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