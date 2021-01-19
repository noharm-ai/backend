from .main import db
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import deferred
from sqlalchemy import inspect

class ClinicalNotes(db.Model):
    __tablename__ = 'evolucao'

    id = db.Column("fkevolucao", db.Integer, primary_key=True)
    admissionNumber = db.Column('nratendimento', db.Integer, nullable=False)
    text = db.Column("texto", db.String, nullable=False)
    date = db.Column('dtevolucao', db.DateTime, nullable=False)
    prescriber = db.Column('prescritor', db.String, nullable=True)
    position = db.Column('cargo', db.String, nullable=True)
    features = db.Column("indicadores", postgresql.JSON, nullable=False)
    update = db.Column("update_at", db.DateTime, nullable=True)
    user = db.Column("update_by", db.Integer, nullable=True)

    def exists():
        tMap = db.session.connection()._execution_options.get("schema_translate_map", { None: None })
        schemaName = tMap[None]
        return db.engine.has_table('evolucao', schema=schemaName)

    def getIfExists(admissionNumber):
        if ClinicalNotes.exists():
            return ClinicalNotes.query.filter(ClinicalNotes.admissionNumber==admissionNumber).count()
        else:
            return None
