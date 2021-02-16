from models.main import *
from models.appendix import *
from flask import Blueprint, request
from flask_jwt_extended import (jwt_required, get_jwt_identity)
from .utils import tryCommit
from datetime import datetime

app_mem = Blueprint('app_mem',__name__)

@app_mem.route('/memory/<string:kind>', methods=['GET'])
@jwt_required()
def getMemory(kind):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    memList = Memory.query.filter(Memory.kind==kind).all()

    results = []
    for m in memList:
        results.append({
            'key': m.key,
            'value': m.value
        })
    
    return {
        'status': 'success',
        'data': results
    }, status.HTTP_200_OK

@app_mem.route('/memory/', methods=['PUT'])
@app_mem.route('/memory/<int:idMemory>', methods=['PUT'])
@jwt_required()
def setSubstance(idMemory=None):
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    newMem = False
    if idMemory:
        mem = Memory.query.get(idMemory)
        if (mem is None):
            return { 'status': 'error', 'message': 'Memória Inexistente!' }, status.HTTP_400_BAD_REQUEST
    else:
        newMem = True
        mem = Memory()

    mem.kind = data.get('type')
    mem.value = data.get('value')
    mem.update = datetime.today()
    mem.user = user.id

    if newMem: 
        db.session.add(mem)
        db.session.flush()

    return tryCommit(db, mem.key)