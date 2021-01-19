from models.main import dbSession, User
from models.notes import ClinicalNotes
from flask import Blueprint, request
from flask_api import status
from flask_jwt_extended import (jwt_required, get_jwt_identity)
from .utils import tryCommit

app_note = Blueprint('app_note',__name__)

@app_note.route('/notes/<int:admissionNumber>', methods=['GET'])
@jwt_required
def getNotes(admissionNumber):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    if ClinicalNotes.exists():
    
        notes = ClinicalNotes.query.filter(ClinicalNotes.admissionNumber==admissionNumber).all()

        results = []
        for n in notes:
            results.append({
                'admissionNumber': n.admissionNumber,
                'text': n.text,
                'date': n.date.isoformat(),
                'prescriber': n.prescriber,
                'position': n.position,
                'features': n.features,
                'update': n.update.isoformat(),
                'user': n.user
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