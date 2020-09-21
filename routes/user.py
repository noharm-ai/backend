from models.main import *
from models.appendix import *
from flask import Blueprint, request
from flask_jwt_extended import (jwt_required, get_jwt_identity)
from .utils import tryCommit
from datetime import datetime
from sqlalchemy import func

app_usr = Blueprint('app_usr',__name__)

@app_usr.route("/reports", methods=['GET'])
@jwt_required
def getReports():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    
    if user: 
        return {
            'status': 'success',
            'reports': Memory.getMem('reports', []),
        }, status.HTTP_200_OK 
    else:
        return {
            'status': 'error',
            'message': 'HTTP_401_UNAUTHORIZED'
        }, status.HTTP_401_UNAUTHORIZED

@app_usr.route("/user", methods=['GET'])
@jwt_required
def getUser():
    user = User.find(get_jwt_identity())

    if not user: 
        return { 'status': 'error', 'message': 'Usuário Inexistente!' }, status.HTTP_400_BAD_REQUEST

    return {
        'status': 'success',
        'data': {
            'id': user.id,
            'sign': user.config['sign'] if 'sign' in user.config else ''
        }
    }, status.HTTP_200_OK

@app_usr.route("/user", methods=['PUT'])
@jwt_required
def setUser():
    data = request.get_json()
    user = User.find(get_jwt_identity())

    if not user: 
        return { 'status': 'error', 'message': 'Usuário Inexistente!' }, status.HTTP_400_BAD_REQUEST

    update = {}

    config = user.config or {}
    config['sign'] = data.get('sign', None)
    update['config'] = config

    if 'password' in data.keys():
        update['password'] = func.md5(data.get('password'))

    db.session.query(User)\
              .filter(User.id == user.id)\
              .update(update, synchronize_session='fetch')
    
    return tryCommit(db, user.id)