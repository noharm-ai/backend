from .main import db
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import deferred
from sqlalchemy import inspect, func, desc, distinct
from datetime import datetime, timedelta


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

    medications = db.Column("medicamentos", db.Integer, nullable=True)
    complication = db.Column("complicacoes", db.Integer, nullable=True)
    symptoms = db.Column("sintomas", db.Integer, nullable=True)
    diseases = db.Column("doencas", db.Integer, nullable=True)
    info = db.Column("dados", db.Integer, nullable=True)
    conduct = db.Column("conduta", db.Integer, nullable=True)
    signs = db.Column("sinais", db.Integer, nullable=True)
    allergy = db.Column("alergia", db.Integer, nullable=True)
    dialysis = db.Column("dialise", db.Integer, nullable=True)
    names = db.Column("nomes", db.Integer, nullable=True)

    signsText = db.Column("sinaistexto", db.String, nullable=True)
    infoText = db.Column("dadostexto", db.String, nullable=True)
    allergyText = db.Column("alergiatexto", db.String, nullable=True)
    dialysisText = db.Column("dialisetexto", db.String, nullable=True)

    isExam = db.Column("exame", db.Boolean, nullable=False)
    # primary care columns
    form = deferred(db.Column("formulario", postgresql.JSON, nullable=True))
    template = deferred(db.Column("template", postgresql.JSON, nullable=True))

    summary = deferred(db.Column("sumario", postgresql.JSONB, nullable=True))

    def exists():
        return True

    def getCountIfExists(admissionNumber, pmc=False):
        empty_return = [
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        ]

        if ClinicalNotes.exists():
            qNotes = (
                db.session.query(
                    ClinicalNotes.admissionNumber,
                    func.sum(ClinicalNotes.medications),
                    func.sum(ClinicalNotes.complication),
                    func.sum(ClinicalNotes.symptoms),
                    func.sum(ClinicalNotes.diseases),
                    func.sum(ClinicalNotes.info),
                    func.sum(ClinicalNotes.conduct),
                    func.sum(ClinicalNotes.signs),
                    func.sum(ClinicalNotes.allergy),
                    func.count().label("total"),
                    func.sum(ClinicalNotes.dialysis),
                )
                .select_from(ClinicalNotes)
                .filter(ClinicalNotes.admissionNumber == admissionNumber)
                .filter(ClinicalNotes.isExam == None)
            )

            if not pmc:
                qNotes = qNotes.filter(
                    ClinicalNotes.date > (datetime.today() - timedelta(days=6))
                )

            stats_return = qNotes.group_by(ClinicalNotes.admissionNumber).first()

            return stats_return if stats_return else empty_return

        else:
            return empty_return

    def getTotalIfExists(admissionNumber, admission_date=None):
        if ClinicalNotes.exists():
            cutoff_date = (
                datetime.today() - timedelta(days=120)
                if admission_date == None
                else admission_date
            ) - timedelta(days=1)

            qNotes = (
                db.session.query(
                    func.count().label("total"),
                )
                .select_from(ClinicalNotes)
                .filter(ClinicalNotes.admissionNumber == admissionNumber)
                .filter(ClinicalNotes.isExam == None)
                .filter(ClinicalNotes.date >= cutoff_date)
            )

            total = qNotes.scalar()

            return total
        else:
            return 0

    def getComplicationCountIfExists(admissionNumber):
        if ClinicalNotes.exists():
            return (
                ClinicalNotes.query.filter(
                    ClinicalNotes.admissionNumber == admissionNumber
                )
                .filter(ClinicalNotes.isExam == None)
                .filter(ClinicalNotes.date > (datetime.today() - timedelta(days=6)))
                .filter(ClinicalNotes.complication > 0)
                .count()
            )
        else:
            return None

    def getExamsIfExists(admissionNumber):
        if ClinicalNotes.exists():
            return (
                ClinicalNotes.query.filter(
                    ClinicalNotes.admissionNumber == admissionNumber
                )
                .filter(ClinicalNotes.isExam == True)
                .filter(ClinicalNotes.text != None)
                .filter(ClinicalNotes.date > (datetime.today() - timedelta(days=90)))
                .order_by(desc(ClinicalNotes.date))
                .all()
            )
        else:
            return []

    def getSigns(admissionNumber):
        return (
            db.session.query(ClinicalNotes.signsText, ClinicalNotes.date)
            .select_from(ClinicalNotes)
            .filter(ClinicalNotes.admissionNumber == admissionNumber)
            .filter(func.length(ClinicalNotes.signsText) > 0)
            .filter(ClinicalNotes.date > (datetime.today() - timedelta(days=60)))
            .order_by(desc(ClinicalNotes.date))
            .first()
        )

    def getInfo(admissionNumber):
        return (
            db.session.query(ClinicalNotes.infoText, ClinicalNotes.date)
            .select_from(ClinicalNotes)
            .filter(ClinicalNotes.admissionNumber == admissionNumber)
            .filter(func.length(ClinicalNotes.infoText) > 0)
            .filter(ClinicalNotes.date > (datetime.today() - timedelta(days=60)))
            .order_by(desc(ClinicalNotes.date))
            .first()
        )

    def getAllergies(admissionNumber, admission_date=None):
        cutoff_date = (
            datetime.today() - timedelta(days=120)
            if admission_date == None
            else admission_date
        ) - timedelta(days=1)

        return (
            db.session.query(
                ClinicalNotes.allergyText, func.max(ClinicalNotes.date).label("maxdate")
            )
            .select_from(ClinicalNotes)
            .filter(ClinicalNotes.admissionNumber == admissionNumber)
            .filter(func.length(ClinicalNotes.allergyText) > 0)
            .filter(ClinicalNotes.date >= cutoff_date)
            .group_by(ClinicalNotes.allergyText)
            .order_by(desc("maxdate"))
            .limit(50)
            .all()
        )

    def getDialysis(admissionNumber):
        return (
            db.session.query(
                func.first_value(ClinicalNotes.dialysisText).over(
                    partition_by=func.date(ClinicalNotes.date),
                    order_by=desc(ClinicalNotes.date),
                ),
                func.first_value(ClinicalNotes.date).over(
                    partition_by=func.date(ClinicalNotes.date),
                    order_by=desc(ClinicalNotes.date),
                ),
                func.date(ClinicalNotes.date).label("date"),
            )
            .distinct(func.date(ClinicalNotes.date))
            .filter(ClinicalNotes.admissionNumber == admissionNumber)
            .filter(func.length(ClinicalNotes.dialysisText) > 0)
            .filter(ClinicalNotes.date > func.current_date() - 3)
            .order_by(desc("date"))
            .all()
        )
