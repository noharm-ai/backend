from models.main import db, dbSession, User
from models.notes import ClinicalNotes
from models.prescription import Patient
from flask import Blueprint, request
from flask_api import status
from flask_jwt_extended import (jwt_required, get_jwt_identity)
from .utils import tryCommit
from sqlalchemy import desc, or_
from datetime import datetime, timedelta

app_note = Blueprint('app_note',__name__)

@app_note.route('/notes/<int:admissionNumber>', methods=['GET'])
@jwt_required()
def getNotes(admissionNumber):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    if ClinicalNotes.exists():
    
        pat = Patient.query.get(admissionNumber)
        admDate = pat.admissionDate if pat else datetime.today()
        notes = ClinicalNotes.query\
                .filter(ClinicalNotes.admissionNumber==admissionNumber)\
                .filter(or_(ClinicalNotes.isExam == None, ClinicalNotes.isExam == False))\
                .filter(or_(
                        ClinicalNotes.date > (datetime.today() - timedelta(days=6)),
                        ClinicalNotes.date == admDate
                ))\
                .order_by(desc(ClinicalNotes.date))\
                .all()

        results = []
        for n in notes:
            results.append({
                'id': n.id,
                'admissionNumber': n.admissionNumber,
                'text': n.text,
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