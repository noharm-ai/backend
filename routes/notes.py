import os
from models.main import db, dbSession, User
from models.notes import ClinicalNotes
from models.prescription import Patient
from flask import Blueprint, request
from flask_api import status
from flask_jwt_extended import (jwt_required, get_jwt_identity)
from .utils import tryCommit
from sqlalchemy import desc, or_, func
from sqlalchemy.orm import undefer
from datetime import datetime
from services import clinical_notes_service, memory_service

from exception.validation_error import ValidationError

app_note = Blueprint('app_note',__name__)

#deprecated - use /notes/<int:admissionNumber>/v2
@app_note.route('/notes/<int:admissionNumber>', methods=['GET'])
@jwt_required()
def getNotes(admissionNumber):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    if ClinicalNotes.exists():
        has_primary_care = memory_service.has_feature('PRIMARYCARE')
        limit = 100
        pat = Patient.query.get(admissionNumber)
        admDate = pat.admissionDate if pat else datetime.today()
        query = ClinicalNotes.query\
                .filter(ClinicalNotes.admissionNumber==admissionNumber)\
                .filter(or_(ClinicalNotes.isExam == None, ClinicalNotes.isExam == False))

        query = query.order_by(desc(ClinicalNotes.date))

        if has_primary_care:
            limit = 500
            query.options(undefer("form"), undefer("template"))

        notes = query.filter(func.date(ClinicalNotes.date) > func.date(admDate)).limit(limit).all()
        admission_notes = query.filter(func.date(ClinicalNotes.date) == func.date(admDate)).limit(50).all()
        old_notes = []

        if len(notes) < limit:
            old_notes = query.filter(func.date(ClinicalNotes.date) < func.date(admDate))\
                .limit(limit - len(notes))\
                .all()

        results = []
        for n in notes:
            results.append(convert_notes(n, has_primary_care))

        for n in admission_notes:
            results.append(convert_notes(n, has_primary_care))

        for n in old_notes:
            results.append(convert_notes(n, has_primary_care))

        return {
            'status': 'success',
            'data': results
        }, status.HTTP_200_OK
    
    else:

        return {
            'status': 'error',
            'message': 'Schema não tem evolução!'
        }, status.HTTP_400_BAD_REQUEST
    
@app_note.route('/notes/<int:admissionNumber>/v2', methods=['GET'])
@jwt_required()
def get_notes_v2(admissionNumber):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    has_primary_care = memory_service.has_feature('PRIMARYCARE')
    filter_date = request.args.get('date', None)
    dates = None


    if filter_date is None:
        dates = db.session\
            .query(\
                func.date(ClinicalNotes.date), func.count(), func.sum(ClinicalNotes.diseases),\
                func.sum(ClinicalNotes.complication), func.sum(ClinicalNotes.symptoms),\
                func.sum(ClinicalNotes.conduct)
            )\
            .select_from(ClinicalNotes)\
            .filter(ClinicalNotes.admissionNumber==admissionNumber)\
            .filter(or_(ClinicalNotes.isExam == None, ClinicalNotes.isExam == False))\
            .group_by(func.date(ClinicalNotes.date))\
            .order_by(desc(func.date(ClinicalNotes.date)))\
            .all()
        
        if len(dates) > 0:
            notes = get_notes_by_date(admissionNumber, dates[0][0], has_primary_care)
        else:
            notes = []
    else:
        notes = get_notes_by_date(admissionNumber, filter_date, has_primary_care)

    noteResults = []
    for n in notes:
        noteResults.append(convert_notes(n, has_primary_care))

    dateResults = []
    if dates is not None:
        for d in dates:
            dateResults.append({
                'date': d[0].isoformat(),
                'count': d[1],
                'diseases': d[2],
                'complication': d[3],
                'symptoms': d[4],
                'conduct': d[5],
            })

    return {
        'status': 'success',
        'data': {
            'dates': dateResults,
            'notes': noteResults
        }
    }, status.HTTP_200_OK

def get_notes_by_date(admissionNumber, date, has_primary_care):
    query = ClinicalNotes.query\
            .filter(ClinicalNotes.admissionNumber==admissionNumber)\
            .filter(or_(ClinicalNotes.isExam == None, ClinicalNotes.isExam == False))\
            .filter(func.date(ClinicalNotes.date) == date)
    
    if (has_primary_care):
        query = query.options(undefer("form"), undefer("template"))
    
    return query.order_by(desc(ClinicalNotes.date)).all()

def convert_notes(notes, has_primary_care):
    return {
        'id': notes.id,
        'admissionNumber': notes.admissionNumber,
        'text': notes.text,
        'form': notes.form if has_primary_care else None,
        'template': notes.template if has_primary_care else None,
        'date': notes.date.isoformat(),
        'prescriber': notes.prescriber,
        'position': notes.position,
        'medications': notes.medications,
        'complication': notes.complication,
        'symptoms': notes.symptoms,
        'diseases': notes.diseases,
        'info': notes.info,
        'conduct': notes.conduct,
        'signs': notes.signs,
        'allergy': notes.allergy,
        'names': notes.names,
        'dialysis': notes.dialysis,
    }
        

@app_note.route('/notes/<int:idNote>', methods=['POST'])
@jwt_required()
def changeNote(idNote):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    has_primary_care = memory_service.has_feature('PRIMARYCARE')
    data = request.get_json()

    if not ClinicalNotes.exists():
        return { 'status': 'error', 'message': 'Schema não tem evolução!' }, status.HTTP_400_BAD_REQUEST

    n = ClinicalNotes.query.get(idNote)

    if (n is None):
        return { 'status': 'error', 'message': 'Evolução Inexistente!' }, status.HTTP_400_BAD_REQUEST

    n.update = datetime.today()
    n.user = user.id

    if 'text' in data.keys():
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

    if has_primary_care:
        if 'date' in data.keys() and data.get('date', None) != None:
            n.date = data.get('date')

        if 'form' in data.keys() and data.get('form', None) != None:
            n.form = data.get('form')

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