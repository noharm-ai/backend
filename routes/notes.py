import os
from models.main import db, dbSession, User
from models.notes import ClinicalNotes
from models.prescription import Patient
from flask import Blueprint, request
from flask_api import status
from flask_jwt_extended import (jwt_required, get_jwt_identity)
from .utils import tryCommit
from sqlalchemy import desc, or_
from sqlalchemy.orm import undefer
from datetime import datetime, timedelta
from services import clinical_notes_service, memory_service

from exception.validation_error import ValidationError

app_note = Blueprint('app_note',__name__)

@app_note.route('/notes/<int:admissionNumber>', methods=['GET'])
@jwt_required()
def getNotes(admissionNumber):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    if ClinicalNotes.exists():
        has_primary_care = memory_service.has_feature('PRIMARYCARE')
        pat = Patient.query.get(admissionNumber)
        admDate = pat.admissionDate if pat else datetime.today()
        query = ClinicalNotes.query\
                .filter(ClinicalNotes.admissionNumber==admissionNumber)\
                .filter(or_(ClinicalNotes.isExam == None, ClinicalNotes.isExam == False))

        if not has_primary_care:
            query = query.filter(or_(
                        ClinicalNotes.date > (datetime.today() - timedelta(days=6)),
                        ClinicalNotes.date == admDate))

        query = query.order_by(desc(ClinicalNotes.date))

        if has_primary_care:
            query.options(undefer("form"), undefer("template"))

        notes = query.all()

        results = []
        for n in notes:
            results.append({
                'id': n.id,
                'admissionNumber': n.admissionNumber,
                'text': n.text,
                'form': n.form if has_primary_care else None,
                'template': n.template if has_primary_care else None,
                'date': n.date.isoformat(),
                'prescriber': n.prescriber,
                'position': n.position,
                'medications': n.medications,
                'complication': n.complication,
                'symptoms': n.symptoms,
                'diseases': n.diseases,
                'info': n.info,
                'conduct': n.conduct,
                'signs': n.signs,
                'allergy': n.allergy,
                'names': n.names,
                'dialysis': n.dialysis,
            })

        return {
            'status': 'success',
            'data': results
        }, status.HTTP_200_OK
    
    else:

        return {
            'status': 'error',
            'message': 'Schema não tem evolução!'
        }, status.HTTP_400_BAD_REQUEST

@app_note.route('/notes/<int:idNote>', methods=['POST'])
@jwt_required()
def changeNote(idNote):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    data = request.get_json()

    if not ClinicalNotes.exists():
        return { 'status': 'error', 'message': 'Schema não tem evolução!' }, status.HTTP_400_BAD_REQUEST

    n = ClinicalNotes.query.get(idNote)

    if (n is None):
        return { 'status': 'error', 'message': 'Evolução Inexistente!' }, status.HTTP_400_BAD_REQUEST

    n.update = datetime.today()
    n.user = user.id
    n.text = data.get('text', None)
    n.medications = n.text.count('annotation-medicamentos')
    n.complication = n.text.count('annotation-complicacoes')
    n.symptoms = n.text.count('annotation-sintomas')
    n.diseases = n.text.count('annotation-doencas')
    n.info = n.text.count('annotation-dados')
    n.conduct = n.text.count('annotation-conduta')
    n.signs = n.text.count('annotation-sinais')
    n.allergy = n.text.count('annotation-alergia')
    n.names = n.text.count('annotation-nomes')

    return tryCommit(db, idNote)


@app_note.route('/notes', methods=['POST'])
@jwt_required()
def create():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ['TZ'] = 'America/Sao_Paulo'

    try:
        id = clinical_notes_service.create_clinical_notes(data, user)
    except ValidationError as e:
        return {
            'status': 'error',
            'message': e.message,
            'code': e.code
        }, e.httpStatus

    return tryCommit(db, id, user.permission())