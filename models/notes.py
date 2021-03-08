from .main import db
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import deferred
from sqlalchemy import inspect, func, desc
from datetime import datetime, timedelta

class ClinicalNotes(db.Model):
    __tablename__ = 'evolucao'

    id = db.Column("fkevolucao", db.Integer, primary_key=True)
    admissionNumber = db.Column('nratendimento', db.Integer, nullable=False)
    text = db.Column("texto", db.String, nullable=False)
    date = db.Column('dtevolucao', db.DateTime, nullable=False)
    prescriber = db.Column('prescritor', db.String, nullable=True)
    position = db.Column('cargo', db.String, nullable=True)
    update = db.Column("update_at", db.DateTime, nullable=True)
    user = db.Column("update_by", db.Integer, nullable=True)

    medications = db.Column("medicamentos", db.Integer, nullable=True)
    complication = db.Column("complicacoes", db.Integer, nullable=True)
    symptoms = db.Column("sintomas", db.Integer, nullable=True)
    diseases = db.Column("doencas", db.Integer, nullable=True)
    info = db.Column("dados", db.Integer, nullable=True)
    conduct = db.Column("conduta", db.Integer, nullable=True)
    signs = db.Column("sinais", db.Integer, nullable=True)
    names = db.Column("nomes", db.Integer, nullable=True)

    signsText = db.Column('sinaistexto', db.String, nullable=True)
    infoText = db.Column('dadostexto', db.String, nullable=True)

    def exists():
        tMap = db.session.connection()._execution_options.get("schema_translate_map", { None: None })
        schemaName = tMap[None]
        return db.engine.has_table('evolucao', schema=schemaName)

    def getIfExists(admissionNumber):
        if ClinicalNotes.exists():
            return ClinicalNotes.query\
                    .filter(ClinicalNotes.admissionNumber==admissionNumber)\
                    .filter(ClinicalNotes.date > (datetime.today() - timedelta(days=6)))\
                    .count()
        else:
            return None

    def getSigns(admissionNumber):
        return db.session.query(ClinicalNotes.signsText, ClinicalNotes.date)\
                .select_from(ClinicalNotes)\
                .filter(ClinicalNotes.admissionNumber == admissionNumber)\
                .filter(func.length(ClinicalNotes.signsText) > 0)\
                .order_by(desc(ClinicalNotes.date))\
                .first()

    def getInfo(admissionNumber):
        return db.session.query(ClinicalNotes.infoText, ClinicalNotes.date)\
                .select_from(ClinicalNotes)\
                .filter(ClinicalNotes.admissionNumber == admissionNumber)\
                .filter(func.length(ClinicalNotes.infoText) > 0)\
                .order_by(desc(ClinicalNotes.date))\
                .first()