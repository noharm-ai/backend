from flask import Blueprint, request
from datetime import datetime

from models.main import *
from models.prescription import *
from .utils import tryCommit
from services import prescription_agg_service

from exception.validation_error import ValidationError

app_stc = Blueprint('app_stc',__name__)

@app_stc.route('/static/<string:schema>/prescription/<int:id_prescription>', methods=['GET'])
def computePrescription(schema, id_prescription):
    is_cpoe = request.args.get('cpoe', False)
    out_patient = request.args.get('outpatient', None)

    try:    
        prescription_agg_service.create_agg_prescription_by_prescription(schema, id_prescription, is_cpoe, out_patient)
    except ValidationError as e:
        return {
            'status': 'error',
            'message': e.message,
            'code': e.code
        }, e.httpStatus

    return tryCommit(db, str(id_prescription))

@app_stc.route('/static/<string:schema>/aggregate/<int:admission_number>', methods=['GET'])
def create_aggregated_prescription_by_date(schema, admission_number):
    is_cpoe = request.args.get('cpoe', False)
    str_date = request.args.get('p_date', None)
    p_date = datetime.strptime(str_date, '%Y-%m-%d').date()

    try:    
        prescription_agg_service.create_agg_prescription_by_date(schema, admission_number, p_date, is_cpoe)
    except ValidationError as e:
        return {
            'status': 'error',
            'message': e.message,
            'code': e.code
        }, e.httpStatus

    return tryCommit(db, str(admission_number))