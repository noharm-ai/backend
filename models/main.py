from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, text, and_, or_, desc, asc, distinct, cast
from datetime import date, timedelta
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import deferred
from routes.utils import *
from flask_mail import Mail

db = SQLAlchemy()
mail = Mail()

class dbSession():
    def setSchema(schema):
        db.session.connection(execution_options={'schema_translate_map': {None: schema}})

class User(db.Model):
    __tablename__ = 'usuario'
    __table_args__ = {'schema':'public'}

    id = db.Column("idusuario", db.Integer, primary_key=True)
    name = db.Column('nome', db.String(250), nullable=False)
    email = db.Column("email", db.String(254), unique=True, nullable=False)
    password = db.Column('senha', db.String(128), nullable=False)
    schema = db.Column("schema", db.String, nullable=False)
    config = db.Column("config", postgresql.JSON, nullable=False)

    def find(id):
        db_session = db.create_scoped_session()
        return db_session.query(User).filter(User.id == id).first()

    def authenticate(email, password):
        return User.query.filter_by(email=email, password=func.md5(password)).first()

    def permission(self):
        roles = self.config['roles'] if self.config and 'roles' in self.config else []
        return ('suporte' not in roles)

class Substance(db.Model):
    __tablename__ = 'substancia'
    __table_args__ = {'schema':'public'}

    id = db.Column("sctid", db.Integer, primary_key=True)
    name = db.Column('nome', db.String(255), nullable=False)

class Relation(db.Model):
    __tablename__ = 'relacao'
    __table_args__ = {'schema':'public'}

    sctida = db.Column("sctida", db.Integer, primary_key=True)
    sctidb = db.Column("sctidb", db.Integer, primary_key=True)
    kind = db.Column('tprelacao', db.String(2), primary_key=True)
    text = db.Column('texto', db.String, nullable=True)
    active = db.Column("ativo", db.Boolean, nullable=True)
    update = db.Column("update_at", db.DateTime, nullable=True)
    user = db.Column("update_by", db.Integer, nullable=True)
    creator = db.Column("create_by", db.Integer, nullable=True)

    def findBySctid(sctid, user):
        SubstA = db.aliased(Substance)
        SubstB = db.aliased(Substance)

        relations = db.session.query(Relation, SubstA.name, SubstB.name)\
                    .outerjoin(SubstA, SubstA.id == Relation.sctida)\
                    .outerjoin(SubstB, SubstB.id == Relation.sctidb)\
                    .filter(or_(Relation.sctida == sctid, Relation.sctidb == sctid))\
                    .all()

        results = []
        for r in relations:
            if r[0].sctida == sctid:
                sctidB = r[0].sctidb
                nameB = r[2]
            else:
                sctidB = r[0].sctida
                nameB = r[1]

            results.append({
                'sctidB': sctidB,
                'nameB': strNone(nameB).upper(),
                'type': r[0].kind,
                'text': r[0].text,  
                'active': r[0].active, 
                'editable': bool(r[0].creator == user.id) or (not User.permission(user)),
            })

        results.sort(key=sortRelations)

        return results

class Drug(db.Model):
    __tablename__ = 'medicamento'

    id = db.Column("fkmedicamento", db.Integer, primary_key=True)
    idHospital = db.Column("fkhospital", db.Integer, nullable=False)
    name = db.Column("nome", db.String, nullable=False)
    sctid = db.Column("sctid", db.Integer, nullable=True)

    def getBySegment(idSegment, qDrug=None, idDrug=None):
        segDrubs = db.session.query(PrescriptionAgg.idDrug.label('idDrug'))\
                      .filter(PrescriptionAgg.idSegment == idSegment)\
                      .group_by(PrescriptionAgg.idDrug)\
                      .subquery() # too costly

        segDrubs = db.session.query(Outlier.idDrug.label('idDrug'))\
                      .filter(Outlier.idSegment == idSegment)\
                      .group_by(Outlier.idDrug)\
                      .subquery()

        drugs = Drug.query.filter(Drug.id.in_(segDrubs))

        if qDrug: drugs = drugs.filter(Drug.name.ilike("%"+str(qDrug)+"%"))

        if (len(idDrug)>0): drugs = drugs.filter(Drug.id.in_(idDrug))

        return drugs.order_by(asc(Drug.name)).all()

class DrugAttributes(db.Model):
    __tablename__ = 'medatributos'

    idDrug = db.Column("fkmedicamento", db.Integer, primary_key=True)
    idSegment = db.Column("idsegmento", db.Integer, primary_key=True)
    antimicro = db.Column("antimicro", db.Boolean, nullable=True)
    mav = db.Column("mav", db.Boolean, nullable=True)
    controlled = db.Column("controlados", db.Boolean, nullable=True)
    notdefault = db.Column("naopadronizado", db.Boolean, nullable=True)
    maxDose = db.Column("dosemaxima", db.Float, nullable=True)
    kidney = db.Column("renal", db.Integer, nullable=True)
    liver = db.Column("hepatico", db.Integer, nullable=True)
    platelets = db.Column("plaquetas", db.Integer, nullable=True)
    elderly = db.Column("idoso", db.Boolean, nullable=True)
    tube = db.Column("sonda", db.Boolean, nullable=True)
    division = db.Column("divisor", db.Float, nullable=True)
    useWeight = db.Column("usapeso", db.Boolean, nullable=True)
    idMeasureUnit = db.Column("fkunidademedida", db.String, nullable=True)
    amount = db.Column("concentracao", db.Float, nullable=True)
    amountUnit = db.Column("concentracaounidade", db.String(3), nullable=True)
    whiteList = db.Column("linhabranca", db.Boolean, nullable=True)
    price = db.Column("custo", db.Float, nullable=True)
    maxTime = db.Column("tempotratamento", db.Integer, nullable=True)
    update = db.Column("update_at", db.DateTime, nullable=True)
    user = db.Column("update_by", db.Integer, nullable=True)

class Outlier(db.Model):
    __tablename__ = 'outlier'

    id = db.Column("idoutlier", db.Integer, primary_key=True)
    idDrug = db.Column("fkmedicamento", db.Integer, nullable=False)
    idSegment = db.Column("idsegmento", db.Integer, nullable=False)
    countNum = db.Column("contagem", db.Integer, nullable=True)
    dose = db.Column("doseconv", db.Float, nullable=True)
    frequency = db.Column("frequenciadia", db.Float, nullable=True)
    score = db.Column("escore", db.Integer, nullable=True)
    manualScore = db.Column("escoremanual", db.Integer, nullable=True)
    update = db.Column("update_at", db.DateTime, nullable=True)
    user = db.Column("update_by", db.Integer, nullable=True)

class PrescriptionAgg(db.Model):
    __tablename__ = 'prescricaoagg'

    idHospital = db.Column("fkhospital", db.Integer, nullable=False)
    idDepartment = db.Column("fksetor", db.Integer, primary_key=True)
    idSegment = db.Column("idsegmento", db.Integer, nullable=False)
    idDrug = db.Column("fkmedicamento", db.Integer, primary_key=True)
    idMeasureUnit = db.Column("fkunidademedida", db.String, nullable=False)
    idFrequency = db.Column("fkfrequencia", db.String, primary_key=True)
    dose = db.Column("dose", db.Float, primary_key=True)
    doseconv = db.Column("doseconv", db.Float, nullable=True)
    frequency = db.Column("frequenciadia", db.Float, nullable=True)
    countNum = db.Column("contagem", db.Integer, nullable=True)