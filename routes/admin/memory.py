import os
from flask import Blueprint, request
from flask_jwt_extended import (jwt_required, get_jwt_identity)

from flask_api import status
from models.main import *
from models.appendix import *
from models.segment import *
from models.prescription import *
from services.admin import memory_service
from exception.validation_error import ValidationError

app_admin_memory = Blueprint('app_admin_memory',__name__)

@app_admin_memory.route('/admin/memory', methods=['GET'])
@jwt_required()
def get_memory_itens():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    list = memory_service.get_admin_memory_itens(user)

    return {
        'status': 'success',
        'data': list
    }, status.HTTP_200_OK
    

@app_admin_memory.route('/admin/memory', methods=['PUT'])
@jwt_required()
def update_memory_item():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ['TZ'] = 'America/Sao_Paulo'

    try:
        key =  memory_service.update_memory(\
            data.get('key', None), data.get('kind', None), data.get('value', None), user\
        )
    except ValidationError as e:
        return {
            'status': 'error',
            'message': str(e),
            'code': e.code
        }, e.httpStatus

    return tryCommit(db, key)