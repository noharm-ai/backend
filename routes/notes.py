from models.main import dbSession, User
from models.notes import ClinicalNotes
from flask import Blueprint, request
from flask_api import status
from flask_jwt_extended import (jwt_required, get_jwt_identity)
from .utils import tryCommit
from sqlalchemy import desc
from datetime import datetime, timedelta

app_note = Blueprint('app_note',__name__)

@app_note.route('/notes/<int:admissionNumber>', methods=['GET'])
@jwt_required()
def getNotes(admissionNumber):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    if ClinicalNotes.exists():
    
        notes = ClinicalNotes.query\
                .filter(ClinicalNotes.admissionNumber==admissionNumber)\
                .filter(ClinicalNotes.date > (datetime.today() - timedelta(days=2)))\
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
                'position': n.position
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