import os
from flask import Blueprint, request
from flask_jwt_extended import (jwt_required, get_jwt_identity)

from flask_api import status
from models.main import *
from models.appendix import *
from models.segment import *
from models.prescription import *
from services.admin import intervention_reason_service
from exception.validation_error import ValidationError

app_admin_freq = Blueprint('app_admin_freq',__name__)

@app_admin_freq.route('/admin/intervention-reason', methods=['GET'])
@jwt_required()
def get_records():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    list = intervention_reason_service.get_reasons()

    return {
        'status': 'success',
        'data': intervention_reason_service.list_to_dto(list)
    }, status.HTTP_200_OK
    

@app_admin_freq.route('/admin/intervention-reason', methods=['PUT'])
@jwt_required()
def update_record():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ['TZ'] = 'America/Sao_Paulo'

    try:
        reason =  intervention_reason_service.update_reason(\
            data.get('id', None),\
            data_to_object(data),\
            user\
        )
    except ValidationError as e:
        return {
            'status': 'error',
            'message': str(e),
            'code': e.code
        }, e.httpStatus

    return tryCommit(db, intervention_reason_service.list_to_dto([reason]))

@app_admin_freq.route('/admin/intervention-reason', methods=['POST'])
@jwt_required()
def create_record():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ['TZ'] = 'America/Sao_Paulo'

    try:
        reason =  intervention_reason_service.create_reason(\
            data_to_object(data),\
            user\
        )
    except ValidationError as e:
        return {
            'status': 'error',
            'message': str(e),
            'code': e.code
        }, e.httpStatus

    return tryCommit(db, intervention_reason_service.list_to_dto([reason]))

def data_to_object(data) -> InterventionReason:
    return InterventionReason(\
        description = data.get('description', None),\
        mamy = data.get('parent', None),\
        active = data.get('active', None),\
    )