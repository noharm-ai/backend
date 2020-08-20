from .main import db
from sqlalchemy.dialects import postgresql

class Department(db.Model):
    __tablename__ = 'setor'

    id = db.Column("fksetor", db.Integer, primary_key=True)
    idHospital = db.Column("fkhospital", db.Integer, nullable=False)
    name = db.Column("nome", db.String, nullable=False)

    def getAll():
        return Department.query.all()

class SegmentDepartment(db.Model):
    __tablename__ = 'segmentosetor'

    id = db.Column("idsegmento", db.Integer, primary_key=True)
    idHospital = db.Column("fkhospital", db.Integer, primary_key=True)
    idDepartment = db.Column("fksetor", db.Integer, primary_key=True)

class MeasureUnit(db.Model):
    __tablename__ = 'unidademedida'

    id = db.Column("fkunidademedida", db.String, primary_key=True)
    idHospital = db.Column("fkhospital", db.Integer, nullable=False)
    description = db.Column("nome", db.String, nullable=False)

class MeasureUnitConvert(db.Model):
    __tablename__ = 'unidadeconverte'

    idMeasureUnit = db.Column("fkunidademedida", db.String, primary_key=True)
    idDrug = db.Column("fkmedicamento", db.Integer, primary_key=True)
    idSegment = db.Column("idsegmento", db.Integer, primary_key=True)
    factor = db.Column("fator", db.String, nullable=False)

class InterventionReason(db.Model):
    __tablename__ = 'motivointervencao'

    id = db.Column("idmotivointervencao", db.Integer, primary_key=True)
    description = db.Column("nome", db.String, nullable=False)
    mamy = db.Column("idmotivomae", db.Integer, nullable=False)

    def findAll():
        im = db.aliased(InterventionReason)

        return db.session.query(InterventionReason, im.description)\
                .outerjoin(im, im.id == InterventionReason.mamy)\
                .order_by(InterventionReason.description)\
                .all()

class Frequency(db.Model):
    __tablename__ = 'frequencia'

    id = db.Column("fkfrequencia", db.String, primary_key=True)
    description = db.Column("nome", db.String, nullable=False)

class Notes(db.Model):
    __tablename__ = 'observacao'

    idOutlier = db.Column("idoutlier", db.Integer, primary_key=True)
    idPrescriptionDrug = db.Column("fkpresmed", db.Integer, primary_key=True)
    admissionNumber = db.Column('nratendimento', db.Integer, nullable=False)
    idSegment = db.Column("idsegmento", db.Integer, nullable=False)
    idDrug = db.Column("fkmedicamento", db.Integer, nullable=False)
    dose = db.Column("doseconv", db.Float, nullable=True)
    frequency = db.Column("frequenciadia", db.Float, nullable=True)
    notes = db.Column('text', db.String, nullable=True)
    update = db.Column("update_at", db.DateTime, nullable=True)
    user = db.Column("update_by", db.Integer, nullable=True)

class Memory(db.Model):
    __tablename__ = 'memoria'

    key = db.Column("idmemoria", db.Integer, primary_key=True, autoincrement=True)
    kind = db.Column("tipo", db.String(100), nullable=False)
    value = db.Column("valor", postgresql.JSON, nullable=False)
    update = db.Column("update_at", db.DateTime, nullable=False)
    user = db.Column("update_by", db.Integer, nullable=False)

    def getMem(kind, default):
        mem = Memory.query.filter_by(kind=kind).first()
        return mem.value if mem else default