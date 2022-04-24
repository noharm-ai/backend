from flask_api import status
from models.main import *
from flask import Blueprint
from flask_jwt_extended import (jwt_required, get_jwt_identity)
from .utils import *

from services.drug_service import getPreviouslyPrescribedUnits, getUnits, getPreviouslyPrescribedFrequencies, getFrequencies

app_drugs = Blueprint('app_drugs',__name__)

@app_drugs.route('/drugs/resources/<int:idDrug>/<int:idSegment>/<int:idHospital>', methods=['GET'])
@jwt_required()
def getDrugSummary(idDrug, idSegment, idHospital):
  user = User.find(get_jwt_identity())
  dbSession.setSchema(user.schema)
  
  drug = Drug.query.get(idDrug)

  prescribedUnits = getPreviouslyPrescribedUnits(idDrug, idSegment)
  allUnits = getUnits(idHospital)

  unitResults = []
  for u in prescribedUnits:
    unitResults.append({
      'id': u.id,
      'description': u.description,
      'amount': u.count
    })
  for u in allUnits:
    unitResults.append({
      'id': u.id,
      'description': u.description,
      'amount': 0
    })

  prescribedFrequencies = getPreviouslyPrescribedFrequencies(idDrug, idSegment)
  allFrequencies = getFrequencies(idHospital)

  frequencyResults = []
  for f in prescribedFrequencies:
    frequencyResults.append({
      'id': f.id,
      'description': f.description,
      'amount': f.count
    })
  for f in allFrequencies:
    frequencyResults.append({
      'id': f.id,
      'description': f.description,
      'amount': 0
    })

  results = {
    'drug': {
      'id': idDrug,
      'name': drug.name if drug else ''
    },
    'units': unitResults,
    'frequencies': frequencyResults
  }

  return {
    'status': 'success',
    'data': results
  }, status.HTTP_200_OK