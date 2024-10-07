from datetime import date, timedelta
from sqlalchemy import and_, desc, asc

from .main import db
from utils import examutils, dateutils


class Segment(db.Model):
    __tablename__ = "segmento"

    id = db.Column("idsegmento", db.BigInteger, primary_key=True)
    description = db.Column("nome", db.String, nullable=False)
    status = db.Column("status", db.Integer, nullable=False)


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

    def findByPatient(idPatient):
        return (
            db.session.query(Exams)
            .filter(Exams.idPatient == idPatient)
            .filter(Exams.date >= (date.today() - timedelta(days=90)))
            .order_by(asc(Exams.typeExam), desc(Exams.date))
            .all()
        )

    def findLatestByAdmission(patient, idSegment, prevEx=False):
        examLatest = (
            db.session.query(Exams.typeExam.label("typeExam"), Exams.date.label("date"))
            .select_from(Exams)
            .distinct(Exams.typeExam)
            .filter(Exams.idPatient == patient.idPatient)
            .filter(Exams.date >= (date.today() - timedelta(days=90)))
            .order_by(Exams.typeExam, Exams.date.desc())
            .subquery()
        )

        el = db.aliased(examLatest)

        results = (
            Exams.query.distinct(Exams.typeExam)
            .filter(Exams.idPatient == patient.idPatient)
            .filter(Exams.date >= (date.today() - timedelta(days=5)))
            .order_by(Exams.typeExam, Exams.date.desc())
        )

        resultsPrev = (
            Exams.query.distinct(Exams.typeExam)
            .join(el, and_(Exams.typeExam == el.c.typeExam, Exams.date < el.c.date))
            .filter(Exams.idPatient == patient.idPatient)
            .filter(Exams.date >= (date.today() - timedelta(days=90)))
            .order_by(Exams.typeExam, Exams.date.desc())
        )

        segExam = SegmentExam.refDict(idSegment)
        age = dateutils.data2age(
            patient.birthdate.isoformat()
            if patient.birthdate
            else date.today().isoformat()
        )

        exams = {}
        for e in segExam:
            examEmpty = {
                "value": None,
                "alert": False,
                "ref": None,
                "name": None,
                "unit": None,
                "delta": None,
            }
            examEmpty["date"] = None
            examEmpty["min"] = segExam[e].min
            examEmpty["max"] = segExam[e].max
            examEmpty["name"] = segExam[e].name
            examEmpty["initials"] = segExam[e].initials
            if segExam[e].initials.lower().strip() == "creatinina":
                exams["cr"] = examEmpty
            else:
                exams[e.lower()] = examEmpty

        examPrev = {}
        if prevEx:
            for e in resultsPrev:
                examPrev[e.typeExam] = e.value

        examsExtra = {}
        for e in results:
            prevValue = (
                examPrev[e.typeExam]
                if prevEx and e.typeExam in examPrev.keys()
                else None
            )

            if e.typeExam.lower() not in [
                "mdrd",
                "ckd",
                "ckd21",
                "cg",
                "swrtz2",
                "swrtz1",
            ]:
                exams[e.typeExam.lower()] = examutils.formatExam(
                    e, e.typeExam.lower(), segExam, prevValue
                )

            if e.typeExam.lower() in segExam:
                if (
                    segExam[e.typeExam.lower()].initials.lower().strip() == "creatinina"
                    and "cr" in exams
                    and exams["cr"]["value"] == None
                ):
                    exams["cr"] = examutils.formatExam(
                        e, e.typeExam.lower(), segExam, prevValue
                    )
                if segExam[e.typeExam.lower()].initials.lower().strip() == "tgo":
                    examsExtra["tgo"] = examutils.formatExam(
                        e, e.typeExam.lower(), segExam, prevValue
                    )
                if segExam[e.typeExam.lower()].initials.lower().strip() == "tgp":
                    examsExtra["tgp"] = examutils.formatExam(
                        e, e.typeExam.lower(), segExam, prevValue
                    )
                if segExam[e.typeExam.lower()].initials.lower().strip() == "plaquetas":
                    examsExtra["plqt"] = examutils.formatExam(
                        e, e.typeExam.lower(), segExam, prevValue
                    )

        if "cr" in exams:
            if age > 17:
                if "mdrd" in exams:
                    exams["mdrd"] = examutils.mdrd_calc(
                        exams["cr"]["value"],
                        patient.birthdate,
                        patient.gender,
                        patient.skinColor,
                    )
                if "cg" in exams:
                    exams["cg"] = examutils.cg_calc(
                        exams["cr"]["value"],
                        patient.birthdate,
                        patient.gender,
                        patient.weight,
                    )
                if "ckd" in exams:
                    exams["ckd"] = examutils.ckd_calc(
                        exams["cr"]["value"],
                        patient.birthdate,
                        patient.gender,
                        patient.skinColor,
                        patient.height,
                        patient.weight,
                    )
                if "ckd21" in exams:
                    exams["ckd21"] = examutils.ckd_calc_21(
                        exams["cr"]["value"], patient.birthdate, patient.gender
                    )
            else:
                if "swrtz2" in exams:
                    exams["swrtz2"] = examutils.schwartz2_calc(
                        exams["cr"]["value"], patient.height
                    )

                if "swrtz1" in exams:
                    exams["swrtz1"] = examutils.schwartz1_calc(
                        exams["cr"]["value"],
                        patient.birthdate,
                        patient.gender,
                        patient.height,
                    )

        return dict(exams, **examsExtra)
