from flask import request, url_for, jsonify
from flask_api import FlaskAPI, status, exceptions
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from flask_jwt_extended import (create_access_token, create_refresh_token, jwt_required, jwt_refresh_token_required, get_jwt_identity, get_raw_jwt)
from models import db, User, Patient, Prescription, PrescriptionDrug, InterventionReason, Intervention
from config import Config

app = FlaskAPI(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = Config.MYSQL_CONNECTION_STRING
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_POOL_RECYCLE'] = 299
app.config['SQLALCHEMY_POOL_TIMEOUT'] = 20
app.config['JWT_SECRET_KEY'] = Config.SECRET_KEY
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = Config.JWT_ACCESS_TOKEN_EXPIRES
app.config['JWT_REFRESH_TOKEN_EXPIRES'] = Config.JWT_REFRESH_TOKEN_EXPIRES

jwt = JWTManager(app)
db.init_app(app)

@app.route("/authenticate", methods=['POST'])
def auth():
    data = request.get_json()

    user = User.authenticate(data.get('email'), data.get('password'))
    db.engine.dispose()
    
    if user is None:
        return {
          'status': 'error',
          'message': 'Usuário inválido',
        }, status.HTTP_401_UNAUTHORIZED
    else:
        access_token = create_access_token(identity = user.id)
        refresh_token = create_refresh_token(identity = user.id)

        return {
          'status': 'success',
          'userName': user.name,
          'access_token': access_token,
          'refresh_token': refresh_token
        }, status.HTTP_200_OK

@app.route("/refresh-token", methods=['POST'])
@jwt_refresh_token_required
def refreshToken():
    current_user = get_jwt_identity()
    access_token = create_access_token(identity = current_user)
    return {'access_token': access_token}


@app.route("/patients", methods=['GET'])
@jwt_required
def getPatients():
    user = User.find(get_jwt_identity())
    patients = Patient.getPatients(\
      user.idHospital, name = request.args.get('name'), order = request.args.get('order'), direction = request.args.get('direction'),\
      limit = request.args.get('limit')
    )
    db.engine.dispose()

    results = []
    for p in patients:
        results.append({
          'idPrescription': p[0].id,
          'idPatient': p[0].idPatient,
          'name': p[1].name,
          'date': p[0].date.isoformat(),
          'daysAgo': p[3],
          'risk': p[2].description,
          'prescriptionScore': str(p[4])
        })

    return {
      'status': 'success',
      'data': results
    }, status.HTTP_200_OK

@app.route('/prescription/<int:idPrescription>', methods=['GET'])
@jwt_required
def getPrescription(idPrescription):
    prescription = Prescription.getPrescription(idPrescription)

    if (prescription is None):
        return {}, status.HTTP_204_NO_CONTENT

    drugs = PrescriptionDrug.findByPrescription(idPrescription)
    db.engine.dispose()
    
    pDrugs = []
    for pd in drugs:
        pDrugs.append({
          'idPrescriptionDrug': pd[0].id,
          'idDrug': pd[0].idDrug,
          'drug': pd[1].name,
          'dose': pd[0].dose,
          'measureUnit': pd[2].description,
          'frequency': pd[5].description,
          'administration': pd[3].description,
          'score': str(pd[4])
        })
    
    return {
      'status': 'success',
      'data': {
        'idPrescription': prescription[0].id,
        'idPatient': prescription[1].id,
        'idHospital': prescription[1].idHospital,
        'name': prescription[1].name,
        'date': prescription[0].date.isoformat(),
        'risk': prescription[2].description,
        'daysAgo': prescription[3],
        'prescriptionScore': str(prescription[4]),
        'prescription': pDrugs
      }
    }, status.HTTP_200_OK

@app.route("/intervention/reasons", methods=['GET'])
@jwt_required
def getInterventionReasons():
    results = InterventionReason.query.order_by(InterventionReason.description).all()
    db.engine.dispose()

    iList = []
    for i in results:
      iList.append({
        'id': i.id,
        'description': i.description
      })

    return {
      'status': 'success',
      'data': iList
    }, status.HTTP_200_OK

@app.route('/intervention', methods=['POST'])
@jwt_required
def createIntervention():
    user = User.find(get_jwt_identity())
    data = request.get_json()

    i = Intervention()
    i.idUser = user.id
    i.idPrescriptionDrug = data.get('idPrescriptionDrug', None)
    i.idInterventionReason = data.get('idInterventionReason', None)
    i.propagation = data.get('propagation', None)
    i.observation = data.get('observation', None)

    #TODO: remover
    i.idPrescription = 17
    i.idDrug = 1

    try:
        i.save()
        db.engine.dispose()

        return {
          'status': 'success',
          'data': i.id
        }, status.HTTP_200_OK
    except AssertionError as e:
      db.engine.dispose()

      return {
        'status': 'error',
        'message': str(e)
      }, status.HTTP_400_BAD_REQUEST

if __name__ == "__main__":
    app.run(debug=True)