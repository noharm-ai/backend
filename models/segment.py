from sqlalchemy import asc

from .main import db


class Segment(db.Model):
    __tablename__ = "segmento"

    id = db.Column("idsegmento", db.BigInteger, primary_key=True)
    description = db.Column("nome", db.String, nullable=False)
    status = db.Column("status", db.Integer, nullable=False)
    type = db.Column("tp_segmento", db.Integer, nullable=True)


class SegmentExam(db.Model):
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

    def refDict(idSegment):
        exams = (
            SegmentExam.query.filter(SegmentExam.idSegment == idSegment)
            .filter(SegmentExam.active == True)
            .order_by(asc(SegmentExam.order))
            .all()
        )

        results = {}
        for e in exams:
            results[e.typeExam.lower()] = e
            if e.initials.lower().strip() == "creatinina":
                results["cr"] = e

        return results


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
