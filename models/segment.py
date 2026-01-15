from .main import db


class Segment(db.Model):
    """Table segmento"""

    __tablename__ = "segmento"

    id = db.Column("idsegmento", db.BigInteger, primary_key=True)
    description = db.Column("nome", db.String, nullable=False)
    status = db.Column("status", db.Integer, nullable=False)
    type = db.Column("tp_segmento", db.Integer, nullable=True)
    cpoe = db.Column("cpoe", db.Boolean, nullable=False)
    cpoe_outpatient_clinic = db.Column("cpoe_ambulatorio", db.Boolean, nullable=False)


class SegmentExam(db.Model):
    """Table segmentoexame"""

    __tablename__ = "segmentoexame"

    idSegment = db.Column("idsegmento", db.BigInteger, primary_key=True)
    typeExam = db.Column("tpexame", db.String(100), primary_key=True)
    initials = db.Column("abrev", db.String(50), nullable=False)
    name = db.Column("nome", db.String(250), nullable=False)
    min = db.Column("min", db.Float, nullable=False)
    max = db.Column("max", db.Float, nullable=False)
    ref = db.Column("referencia", db.String(250), nullable=False)
    order = db.Column("posicao", db.Integer, nullable=False)
    active = db.Column("ativo", db.Boolean, nullable=False)
    update = db.Column("update_at", db.DateTime, nullable=False)
    user = db.Column("update_by", db.BigInteger, nullable=False)


class Hospital(db.Model):
    __tablename__ = "hospital"

    id = db.Column("fkhospital", db.BigInteger, primary_key=True)
    name = db.Column("nome", db.String, nullable=False)


class Exams(db.Model):
    __tablename__ = "exame"

    idExame = db.Column("fkexame", db.BigInteger, primary_key=True)
    idPatient = db.Column("fkpessoa", db.BigInteger, nullable=False)
    idPrescription = db.Column("fkprescricao", db.BigInteger, nullable=False)
    admissionNumber = db.Column("nratendimento", db.BigInteger, nullable=False)
    date = db.Column("dtexame", db.DateTime, nullable=False)
    typeExam = db.Column("tpexame", db.String, primary_key=True)
    value = db.Column("resultado", db.Float, nullable=False)
    unit = db.Column("unidade", db.String, nullable=True)
    created_by = db.Column("created_by", db.Integer, nullable=True)
