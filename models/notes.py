from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import deferred

from .main import db


class ClinicalNotes(db.Model):
    __tablename__ = "evolucao"

    id = db.Column("fkevolucao", db.BigInteger, primary_key=True)
    admissionNumber = db.Column("nratendimento", db.BigInteger, nullable=False)
    text = db.Column("texto", db.String, nullable=False)
    date = db.Column("dtevolucao", db.DateTime, nullable=False)
    prescriber = db.Column("prescritor", db.String, nullable=True)
    position = db.Column("cargo", db.String, nullable=True)
    update = db.Column("update_at", db.DateTime, nullable=True)
    user = db.Column("update_by", db.BigInteger, nullable=True)

    allergy = db.Column("alergia", db.Integer, nullable=True)
    dialysis = db.Column("dialise", db.Integer, nullable=True)

    signsText = db.Column("sinaistexto", db.String, nullable=True)
    infoText = db.Column("dadostexto", db.String, nullable=True)
    allergyText = db.Column("alergiatexto", db.String, nullable=True)
    dialysisText = db.Column("dialisetexto", db.String, nullable=True)

    isExam = db.Column("exame", db.Boolean, nullable=False)
    # primary care columns
    form = deferred(db.Column("formulario", postgresql.JSON, nullable=True))
    template = deferred(db.Column("template", postgresql.JSON, nullable=True))

    summary = deferred(db.Column("sumario", postgresql.JSONB, nullable=True))
    annotations = deferred(db.Column("anotacoes", postgresql.JSONB, nullable=True))
