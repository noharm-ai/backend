from models.main import *
from models.appendix import *
from models.segment import *
from models.prescription import *
from flask import Blueprint, request
from flask_jwt_extended import (jwt_required)
from .utils import *

from services import prescription_drug_edit_service
from converter import prescription_drug_converter
from annotation.api_endpoint import api_endpoint

app_pres_crud = Blueprint('app_pres_crud',__name__)

@app_pres_crud.route('/editPrescription/drug/<int:idPrescriptionDrug>', methods=['PUT'])
@jwt_required()
@api_endpoint()
def update_prescription_drug(idPrescriptionDrug):
    pd = prescription_drug_edit_service.update(idPrescriptionDrug, request.get_json())
    return prescription_drug_converter.to_dto(pd)

@app_pres_crud.route('/editPrescription/drug', methods=['POST'])
@jwt_required()
@api_endpoint()
def create_prescription_drug():
    pd = prescription_drug_edit_service.create(request.get_json())
    return prescription_drug_converter.to_dto(pd)

@app_pres_crud.route('/editPrescription/drug/<int:idPrescriptionDrug>/suspend/<int:suspend>', methods=['PUT'])
@jwt_required()
@api_endpoint()
def suspend_prescription_drug(idPrescriptionDrug, suspend):
    pdUpdate = prescription_drug_edit_service.toggle_suspension(idPrescriptionDrug, True if suspend == 1 else False)

    return {
        'idPrescription': str(pdUpdate.idPrescription),
        'idPrescriptionDrug': str(pdUpdate.id),
        'idDrug': pdUpdate.idDrug,
        'suspended': True if suspend == 1 else False
    }

@app_pres_crud.route('/editPrescription/<int:idPrescription>/copy', methods=['POST'])
@jwt_required()
@api_endpoint()
def copy_prescription(idPrescription):
    data = request.get_json()
    #TODO
    #copyPrescription(idPrescription, user)