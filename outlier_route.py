from __main__ import app
from flask_api import status
from models import db
from flask import request

class Outlier(db.Model):
    __tablename__ = 'outlier_'

    id = db.Column("idoutlier", db.Integer, primary_key=True)
    idDrug = db.Column("fkmedicamento", db.Integer, nullable=False)
    idSegment = db.Column("idsegmento", db.Integer, nullable=False)
    countNum = db.Column("contagem", db.Integer, nullable=True)
    dose = db.Column("dose", db.Integer, nullable=True)
    frequency = db.Column("frequenciadia", db.Integer, nullable=True)
    score = db.Column("escore", db.Integer, nullable=True)
    manualScore = db.Column("escoremanual", db.Integer, nullable=True)
    idUser = db.Column("idusuario", db.Integer, nullable=True)

class Drug(db.Model):
    __tablename__ = 'medicamento_'

    id = db.Column("fkmedicamento", db.Integer, primary_key=True)
    idMeasureUnit = db.Column("fkunidademedida", db.Integer, nullable=False)
    idHospital = db.Column("fkhospital", db.Integer, nullable=False)
    name = db.Column("nome", db.String, nullable=False)

class Departments(db.Model):
    __tablename__ = 'setor'

    id = db.Column("fksetor", db.Integer, primary_key=True)
    idHospital = db.Column("fkhospital", db.Integer, nullable=False)
    name = db.Column("nome", db.String, nullable=False)

class Segment(db.Model):
    __tablename__ = 'segmento_'

    id = db.Column("idsegmento", db.Integer, primary_key=True)
    description = db.Column("nome", db.String, nullable=False)
    minAge = db.Column("idade_min", db.Integer, nullable=False)
    maxAge = db.Column("idade_max", db.Integer, nullable=False)
    minWeight = db.Column("peso_min", db.Float, nullable=False)
    maxWeight = db.Column("peso_max", db.Float, nullable=False)
    status = db.Column("status", db.Float, nullable=False)

@app.route('/outliers/<int:idSegment>/<int:idDrug>', methods=['GET'])
def getOutliers(idSegment=1,idDrug=1):
    Outlier.__table__.schema = 'demo'
    outliers = Outlier.query\
                .filter(Outlier.idSegment == idSegment, Outlier.idDrug == idDrug)\
                .all()
    db.engine.dispose()

    results = []
    for o in outliers:
        results.append({
          'idOutlier': o.id,
          'idDrug': o.idDrug,
          'countNum': o.countNum,
          'dose': o.dose,
          'frequency': o.frequency,
          'score': o.score,
          'manualScore': o.manualScore,
        })

    return {
      'status': 'success',
      'data': results
    }, status.HTTP_200_OK

@app.route('/outliers/<int:idOutlier>', methods=['PUT'])
def setManualOutlier(idOutlier):
    data = request.get_json()

    Outlier.__table__.schema = 'demo'
    o = Outlier.query.get(idOutlier)
    o.idUser = 1
    o.manualScore = data.get('manualScore', None)

    try:
        db.session.commit()

        return {
          'status': 'success',
          'data': o.id
        }, status.HTTP_200_OK
    except AssertionError as e:
      db.engine.dispose()

      return {
        'status': 'error',
        'message': str(e)
      }, status.HTTP_400_BAD_REQUEST
    except Exception as e:
      db.engine.dispose()

      return {
        'status': 'error',
        'message': str(e)
      }, status.HTTP_500_INTERNAL_SERVER_ERROR


@app.route('/drugs', methods=['GET'])
def getDrugs():
    Drug.__table__.schema = 'demo'
    drugs = Drug.query.all()
    db.engine.dispose()

    results = []
    for d in drugs:
        results.append({
          'idDrug': d.id,
          'name': d.name,
        })

    return {
      'status': 'success',
      'data': results
    }, status.HTTP_200_OK

@app.route('/departments', methods=['GET'])
def getDepartments():
    Departments.__table__.schema = 'demo'
    departs = Departments.query.all()
    db.engine.dispose()

    results = []
    for d in departs:
        results.append({
          'idDepartment': d.id,
          'idHospital': d.idHospital,
          'name': d.name,
        })

    return {
      'status': 'success',
      'data': results
    }, status.HTTP_200_OK


@app.route('/segments', methods=['POST'])
@app.route('/segments/<int:idSegment>', methods=['PUT'])
def setSegment(idSegment=None):
    Segment.__table__.schema = 'demo'

    if request.method == 'POST':
        s = Segment()
    elif request.method == 'PUT':
        s = Segment.query.get(idSegment)

    data = request.get_json()
    if 'description' in data: s.description = data.get('description', None)
    if 'minAge' in data: s.minAge = data.get('minAge', None)
    if 'maxAge' in data: s.maxAge = data.get('maxAge', None)
    if 'minWeight' in data: s.minWeight = data.get('minWeight', None)
    if 'maxWeight' in data: s.maxWeight = data.get('maxWeight', None)
    if 'status' in data: s.status = data.get('status', None)

    if request.method == 'POST':
    	db.session.add(s)

    try:
        db.session.commit()

        return {
          'status': 'success',
          'data': s.id
        }, status.HTTP_200_OK
    except AssertionError as e:
      db.engine.dispose()

      return {
        'status': 'error',
        'message': str(e)
      }, status.HTTP_400_BAD_REQUEST
    except Exception as e:
      db.engine.dispose()

      return {
        'status': 'error',
        'message': str(e)
      }, status.HTTP_500_INTERNAL_SERVER_ERROR