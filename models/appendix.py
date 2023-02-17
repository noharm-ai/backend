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
    idHospital = db.Column("fkhospital", db.Integer, nullable=False)
    description = db.Column("nome", db.String, nullable=False)
    mamy = db.Column("idmotivomae", db.Integer, nullable=False)
    active = db.Column("ativo", db.Boolean, nullable=False)
    suspension = db.Column("suspensao", db.Boolean, nullable=False)
    substitution = db.Column("substituicao", db.Boolean, nullable=False)
    relation_type = db.Column("tp_relacao", db.Integer, nullable=False)

class Frequency(db.Model):
    __tablename__ = 'frequencia'

    id = db.Column("fkfrequencia", db.String, primary_key=True)
    idHospital = db.Column("fkhospital", db.Integer, nullable=False)
    description = db.Column("nome", db.String, nullable=False)
    dailyFrequency = db.Column("frequenciadia", db.Float, nullable=True)

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

    def getDefaultNote(sctid):
        result = db.engine.execute('SELECT schema_name FROM information_schema.schemata')
        defaultSchema = 'hsc_test'

        schemaExists = False
        for r in result:
            if r[0] == defaultSchema: schemaExists = True

        if schemaExists:
            db_session = db.create_scoped_session()
            db_session.connection(execution_options={'schema_translate_map': {None: defaultSchema}})
            note = db_session.query(Notes).filter_by(idDrug=sctid, idSegment=5).first()
            return note.notes if note else None
        else:
            return None

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

    def getNameUrl(schema):
        db_session = db.create_scoped_session()
        db_session.connection(execution_options={'schema_translate_map': {None: schema}})
        mem = db_session.query(Memory).filter_by(kind='getnameurl').first()
        return mem.value if mem else {'value':'http://localhost/{idPatient}'}