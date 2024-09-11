from .main import *
from .appendix import *
from .segment import *
from routes.utils import *
from datetime import datetime
from sqlalchemy.orm import deferred, undefer
from sqlalchemy import case, BigInteger, cast, between, outerjoin, literal, Integer
from sqlalchemy.sql.expression import literal_column, case
from functools import partial
from sqlalchemy.dialects.postgresql import TSRANGE

from models.enums import PrescriptionReviewTypeEnum


class Prescription(db.Model):
    __tablename__ = "prescricao"

    id = db.Column("fkprescricao", db.BigInteger, primary_key=True)
    idPatient = db.Column("fkpessoa", db.BigInteger, nullable=False)
    admissionNumber = db.Column("nratendimento", db.BigInteger, nullable=True)
    idHospital = db.Column("fkhospital", db.BigInteger, nullable=False)
    idDepartment = db.Column("fksetor", db.BigInteger, nullable=False)
    idSegment = db.Column("idsegmento", db.BigInteger, nullable=False)
    date = db.Column("dtprescricao", db.DateTime, nullable=False)
    expire = db.Column("dtvigencia", db.DateTime, nullable=True)
    status = db.Column("status", db.String(1), nullable=False)
    bed = db.Column("leito", db.String(16), nullable=True)
    record = db.Column("prontuario", db.Integer, nullable=True)
    features = db.Column("indicadores", postgresql.JSON, nullable=True)
    notes = deferred(db.Column("evolucao", db.String, nullable=True))
    notes_at = db.Column("evolucao_at", db.DateTime, nullable=True)
    prescriber = db.Column("prescritor", db.String, nullable=True)
    agg = db.Column("agregada", db.Boolean, nullable=True)
    aggDeps = deferred(
        db.Column("aggsetor", postgresql.ARRAY(db.BigInteger), nullable=True)
    )
    aggDrugs = deferred(
        db.Column("aggmedicamento", postgresql.ARRAY(db.BigInteger), nullable=True)
    )
    concilia = db.Column("concilia", db.String(1), nullable=True)
    insurance = db.Column("convenio", db.String, nullable=True)
    reviewType = db.Column("tp_revisao", db.Integer, nullable=True)
    update = db.Column("update_at", db.DateTime, nullable=True)
    user = db.Column("update_by", db.BigInteger, nullable=True)

    def getFuturePrescription(idPrescription, admissionNumber):
        return (
            db.session.query(Prescription)
            .filter(Prescription.admissionNumber == admissionNumber)
            .filter(Prescription.id > idPrescription)
            .first()
        )

    def lastDeptbyAdmission(idPrescription, admissionNumber, ref_date):
        return (
            db.session.query(Department.name)
            .select_from(Prescription)
            .outerjoin(
                Department,
                and_(
                    Department.id == Prescription.idDepartment,
                    Department.idHospital == Prescription.idHospital,
                ),
            )
            .filter(Prescription.admissionNumber == admissionNumber)
            .filter(Prescription.id < idPrescription)
            .filter(
                Prescription.date
                > (func.date(ref_date) - func.cast("1 month", INTERVAL))
            )
            .order_by(desc(Prescription.id))
            .first()
        )

    def getPrescriptionBasic():
        return (
            db.session.query(
                Prescription,
                Patient,
                literal("0"),
                literal("0"),
                Department.name.label("department"),
                Segment.description,
                Patient.observation,
                Prescription.notes,
                Patient.alert,
                Prescription.prescriber,
                User.name,
                Prescription.insurance,
            )
            .outerjoin(Patient, Patient.admissionNumber == Prescription.admissionNumber)
            .outerjoin(
                Department,
                and_(
                    Department.id == Prescription.idDepartment,
                    Department.idHospital == Prescription.idHospital,
                ),
            )
            .outerjoin(Segment, Segment.id == Prescription.idSegment)
            .outerjoin(User, Prescription.user == User.id)
        )

    def getPrescription(idPrescription):
        return (
            Prescription.getPrescriptionBasic()
            .filter(Prescription.id == idPrescription)
            .first()
        )

    def getPrescriptionAgg(admissionNumber, aggDate, idSegment):
        return (
            Prescription.getPrescriptionBasic()
            .filter(Prescription.admissionNumber == admissionNumber)
            .filter(
                between(
                    func.date(aggDate),
                    func.date(Prescription.date),
                    func.coalesce(func.date(Prescription.expire), func.date(aggDate)),
                )
            )
            .filter(Prescription.idSegment == idSegment)
            .filter(Prescription.agg == None)
            .filter(Prescription.concilia == None)
            .order_by(asc(Prescription.date))
            .first()
        )

    def shouldUpdate(idPrescription):
        return (
            db.session.query(DrugAttributes.update)
            .select_from(PrescriptionDrug)
            .join(
                DrugAttributes,
                and_(
                    DrugAttributes.idDrug == PrescriptionDrug.idDrug,
                    DrugAttributes.idSegment == PrescriptionDrug.idSegment,
                ),
            )
            .join(Outlier, Outlier.id == PrescriptionDrug.idOutlier)
            .filter(PrescriptionDrug.idPrescription == idPrescription)
            .filter(
                or_(
                    DrugAttributes.update > (datetime.today() - timedelta(minutes=3)),
                    Outlier.update > (datetime.today() - timedelta(minutes=3)),
                )
            )
            .all()
        )

    def getHeaders(admissionNumber, aggDate, idSegment, is_pmc=False, is_cpoe=False):
        q = (
            db.session.query(Prescription, Department.name, User.name)
            .outerjoin(
                Department,
                and_(
                    Department.id == Prescription.idDepartment,
                    Department.idHospital == Prescription.idHospital,
                ),
            )
            .outerjoin(User, Prescription.user == User.id)
            .filter(Prescription.admissionNumber == admissionNumber)
            .filter(Prescription.agg == None)
            .filter(Prescription.concilia == None)
        )

        q = get_period_filter(q, Prescription, aggDate, is_pmc, is_cpoe)

        if not is_cpoe:
            q = q.filter(Prescription.idSegment == idSegment)
        else:
            # discard all suspended
            active_count = (
                db.session.query(func.count().label("count"))
                .filter(PrescriptionDrug.idPrescription == Prescription.id)
                .filter(
                    or_(
                        PrescriptionDrug.suspendedDate == None,
                        func.date(PrescriptionDrug.suspendedDate) >= aggDate,
                    )
                )
                .as_scalar()
            )
            q = q.filter(active_count > 0)

        prescriptions = q.all()

        headers = {}
        for p in prescriptions:
            headers[p[0].id] = {
                "date": p[0].date.isoformat() if p[0].date else None,
                "expire": p[0].expire.isoformat() if p[0].expire else None,
                "status": p[0].status,
                "bed": p[0].bed,
                "prescriber": p[0].prescriber,
                "idSegment": p[0].idSegment,
                "idHospital": p[0].idHospital,
                "idDepartment": p[0].idDepartment,
                "department": p[1],
                "drugs": {},
                "procedures": {},
                "solutions": {},
                "user": p[2],
                "userId": p[0].user,
            }

        return headers

    def checkPrescriptions(
        admissionNumber, aggDate, idSegment, userId, is_cpoe, is_pmc
    ):
        # will be discontinued
        exists = (
            db.session.query(Prescription)
            .filter(Prescription.admissionNumber == admissionNumber)
            .filter(Prescription.status != "s")
            .filter(Prescription.idSegment == idSegment)
            .filter(Prescription.concilia == None)
            .filter(Prescription.agg == None)
        )

        exists = get_period_filter(exists, Prescription, aggDate, is_pmc, is_cpoe)

        db.session.query(Prescription).filter(
            Prescription.admissionNumber == admissionNumber
        ).filter(Prescription.idSegment == idSegment).filter(
            Prescription.agg != None
        ).filter(
            func.date(Prescription.date) == func.date(aggDate)
        ).update(
            {
                "status": "s" if exists.count() == 0 else "0",
                "update": datetime.today(),
                "user": userId,
            },
            synchronize_session="fetch",
        )


class PrescriptionAudit(db.Model):
    __tablename__ = "prescricao_audit"

    id = db.Column(
        "idprescricao_audit", db.BigInteger, nullable=False, primary_key=True
    )
    auditType = db.Column("tp_audit", db.Integer, nullable=False)
    admissionNumber = db.Column("nratendimento", db.BigInteger, nullable=False)
    idPrescription = db.Column("fkprescricao", db.BigInteger, nullable=False)
    prescriptionDate = db.Column("dtprescricao", db.DateTime, nullable=False)
    idDepartment = db.Column("fksetor", db.BigInteger, nullable=False)
    idSegment = db.Column("idsegmento", db.BigInteger, nullable=True)
    totalItens = db.Column("total_itens", db.BigInteger, nullable=False)
    agg = db.Column("agregada", db.Boolean, nullable=True)
    concilia = db.Column("concilia", db.String(1), nullable=True)
    bed = db.Column("leito", db.String, nullable=True)
    extra = db.Column("extra", postgresql.JSON, nullable=True)
    createdAt = db.Column("created_at", db.DateTime, nullable=False)
    createdBy = db.Column("created_by", db.BigInteger, nullable=False)


class Patient(db.Model):
    __tablename__ = "pessoa"

    idPatient = db.Column("fkpessoa", db.BigInteger, nullable=False)
    idHospital = db.Column("fkhospital", db.BigInteger, nullable=False)
    admissionNumber = db.Column("nratendimento", db.BigInteger, primary_key=True)
    admissionDate = db.Column("dtinternacao", db.DateTime, nullable=True)
    birthdate = db.Column("dtnascimento", db.DateTime, nullable=True)
    gender = db.Column("sexo", db.String(1), nullable=True)
    weight = db.Column("peso", db.Float, nullable=True)
    height = db.Column("altura", db.Float, nullable=True)
    weightDate = db.Column("dtpeso", db.DateTime, nullable=True)
    observation = deferred(db.Column("anotacao", db.String, nullable=True))
    skinColor = db.Column("cor", db.String, nullable=True)
    update = db.Column("update_at", db.DateTime, nullable=True)
    user = db.Column("update_by", db.BigInteger, nullable=True)
    alert = deferred(db.Column("alertatexto", db.String, nullable=True))
    alertDate = db.Column("alertadata", db.DateTime, nullable=True)
    alertExpire = db.Column("alertavigencia", db.DateTime, nullable=True)
    alertBy = db.Column("alerta_by", db.BigInteger, nullable=True)
    dischargeReason = db.Column("motivoalta", db.String, nullable=True)
    dischargeDate = db.Column("dtalta", db.DateTime, nullable=True)
    dialysis = db.Column("dialise", db.String(1), nullable=True)
    lactating = db.Column("lactante", db.Boolean, nullable=True)
    pregnant = db.Column("gestante", db.Boolean, nullable=True)

    def findByAdmission(admissionNumber):
        return (
            db.session.query(Patient)
            .filter(Patient.admissionNumber == admissionNumber)
            .first()
        )

    def getPatients(
        idSegment=None,
        idSegmentList=[],
        idDept=[],
        idDrug=[],
        startDate=date.today(),
        endDate=None,
        pending=False,
        agg=False,
        currentDepartment=False,
        concilia=False,
        allDrugs=False,
        is_cpoe=False,
        insurance=None,
        indicators=[],
        frequencies=[],
        patientStatus=None,
        substances=[],
        substanceClasses=[],
        patientReviewType=None,
        drugAttributes=[],
        idPatient=[],
        intervals=[],
        prescriber=None,
        diff=None,
        global_score_min=None,
        global_score_max=None,
        pending_interventions=None,
    ):
        q = (
            db.session.query(
                Prescription,
                Patient,
                Department.name.label("department"),
                func.count().over(),
                (
                    Prescription.features["prescriptionScore"].astext.cast(Integer)
                    + Prescription.features["av"].astext.cast(Integer)
                    + Prescription.features["am"].astext.cast(Integer)
                    + Prescription.features["alertExams"].astext.cast(Integer)
                    + Prescription.features["alerts"].astext.cast(Integer)
                    + Prescription.features["diff"].astext.cast(Integer)
                ).label("globalScore"),
            )
            .outerjoin(Patient, Patient.admissionNumber == Prescription.admissionNumber)
            .outerjoin(
                Department,
                and_(
                    Department.id == Prescription.idDepartment,
                    Department.idHospital == Prescription.idHospital,
                ),
            )
        )

        currentDepartment = bool(int(none2zero(currentDepartment))) and (
            len(idDept) > 0
        )

        if idSegment != None:
            q = q.filter(Prescription.idSegment == idSegment)

        if len(idSegmentList) > 0:
            # refactor
            segments = []
            for s in idSegmentList:
                if s != None and s != "null":
                    segments.append(s)

            if len(segments) > 0:
                q = q.filter(Prescription.idSegment.in_(idSegmentList))

        if len(idDept) > 0:
            idDept = list(map(int, idDept))
            if currentDepartment or bool(int(none2zero(concilia))) == True:
                q = q.filter(Prescription.idDepartment.in_(idDept))
            else:
                q = q.filter(postgresql.array(idDept).overlap(Prescription.aggDeps))

        if len(idDrug) > 0:
            idDrug = list(map(int, idDrug))
            if bool(int(none2zero(allDrugs))):
                q = q.filter(
                    cast(idDrug, postgresql.ARRAY(BigInteger)).contained_by(
                        Prescription.aggDrugs
                    )
                )
            else:
                q = q.filter(
                    cast(idDrug, postgresql.ARRAY(BigInteger)).overlap(
                        Prescription.aggDrugs
                    )
                )

        if bool(int(none2zero(pending))):
            q = q.filter(Prescription.status == "0")

        if patientStatus == "DISCHARGED":
            q = q.filter(Patient.dischargeDate != None)

        if patientStatus == "ACTIVE":
            q = q.filter(Patient.dischargeDate == None)

        if bool(int(none2zero(agg))) and patientReviewType != None:
            if int(patientReviewType) == PrescriptionReviewTypeEnum.PENDING.value:
                q = q.filter(
                    Prescription.reviewType == PrescriptionReviewTypeEnum.PENDING.value
                )

            if int(patientReviewType) == PrescriptionReviewTypeEnum.REVIEWED.value:
                q = q.filter(
                    Prescription.reviewType == PrescriptionReviewTypeEnum.REVIEWED.value
                )

        if bool(int(none2zero(agg))):
            q = q.filter(Prescription.agg == True)

            if is_cpoe:
                q = q.filter(
                    Prescription.date
                    <= func.coalesce(Patient.dischargeDate, Prescription.date)
                )
        else:
            q = q.filter(Prescription.agg == None)

        if bool(int(none2zero(concilia))):
            q = q.filter(Prescription.concilia != None)
        else:
            q = q.filter(Prescription.concilia == None)

        if insurance != None and len(insurance.strip()) > 0:
            q = q.filter(Prescription.insurance.ilike("%" + str(insurance) + "%"))

        if len(indicators) > 0:
            ind_filters = []
            for i in indicators:
                interactions = ["it", "dt", "dm", "iy", "sl", "rx"]
                if i in interactions:
                    ind_filters.append(
                        Prescription.features["alertStats"]["interactions"][
                            i
                        ].as_integer()
                        > 0
                    )
                else:
                    ind_filters.append(
                        Prescription.features["alertStats"][i].as_integer() > 0
                    )

            q = q.filter(or_(*ind_filters))

        if len(drugAttributes) > 0:
            attr_filters = []
            for a in drugAttributes:
                attr_filters.append(
                    Prescription.features["drugAttributes"][a].as_integer() > 0
                )

            q = q.filter(or_(*attr_filters))

        if len(frequencies) > 0:
            q = q.filter(
                cast(Prescription.features["frequencies"], db.String).op("~*")(
                    "|".join(map(re.escape, frequencies))
                )
            )

        if len(substances) > 0:
            elm = db.Column("elm", type_=postgresql.JSONB)
            subs_query = (
                db.session.query(elm.cast(postgresql.TEXT))
                .select_from(
                    func.json_array_elements(
                        Prescription.features["substanceIDs"]
                    ).alias("elm")
                )
                .as_scalar()
            )

            q = q.filter(
                cast(func.array(subs_query), postgresql.ARRAY(BigInteger)).overlap(
                    cast(substances, postgresql.ARRAY(BigInteger))
                )
            )

        if len(substanceClasses) > 0:
            elm_substance_class = db.Column("elmSubstanceClass", type_=postgresql.JSONB)
            subs_query = (
                db.session.query(elm_substance_class.cast(postgresql.TEXT))
                .select_from(
                    func.json_array_elements_text(
                        Prescription.features["substanceClassIDs"]
                    ).alias("elmSubstanceClass")
                )
                .as_scalar()
            )

            q = q.filter(
                cast(func.array(subs_query), postgresql.ARRAY(postgresql.TEXT)).overlap(
                    substanceClasses
                )
            )

        if len(idPatient) > 0:
            q = q.filter(Prescription.idPatient.in_(idPatient))

        if len(intervals) > 0:
            q = q.filter(
                cast(Prescription.features["intervals"], db.String).op("~*")(
                    "|".join(map(re.escape, intervals))
                )
            )

        if diff != None:
            if bool(int(diff)):
                q = q.filter(Prescription.features["diff"].astext.cast(Integer) > 0)
            else:
                q = q.filter(Prescription.features["diff"].astext.cast(Integer) == 0)

        if pending_interventions != None:
            if bool(int(pending_interventions)):
                q = q.filter(
                    Prescription.features["interventions"].astext.cast(Integer) > 0
                )
            else:
                q = q.filter(
                    Prescription.features["interventions"].astext.cast(Integer) == 0
                )

        if global_score_min != None:
            q = q.filter(
                (
                    Prescription.features["prescriptionScore"].astext.cast(Integer)
                    + Prescription.features["av"].astext.cast(Integer)
                    + Prescription.features["am"].astext.cast(Integer)
                    + Prescription.features["alertExams"].astext.cast(Integer)
                    + Prescription.features["alerts"].astext.cast(Integer)
                    + Prescription.features["diff"].astext.cast(Integer)
                )
                >= global_score_min
            )

        if global_score_max != None:
            q = q.filter(
                (
                    Prescription.features["prescriptionScore"].astext.cast(Integer)
                    + Prescription.features["av"].astext.cast(Integer)
                    + Prescription.features["am"].astext.cast(Integer)
                    + Prescription.features["alertExams"].astext.cast(Integer)
                    + Prescription.features["alerts"].astext.cast(Integer)
                    + Prescription.features["diff"].astext.cast(Integer)
                )
                <= global_score_max
            )

        if prescriber != None:
            q = q.filter(Prescription.prescriber.ilike(f"%{prescriber}%"))

        if endDate is None:
            endDate = startDate

        q = q.filter(Prescription.date >= validate(startDate))
        q = q.filter(
            Prescription.date <= (validate(endDate) + timedelta(hours=23, minutes=59))
        )

        if agg:
            q = q.order_by(desc("globalScore"))
        else:
            q = q.order_by(desc(Prescription.date))

        q = q.options(undefer(Patient.observation))

        return q.limit(500).all()


def getDrugHistory(idPrescription, admissionNumber, id_drug, is_cpoe):
    pd1 = db.aliased(PrescriptionDrug)
    pr1 = db.aliased(Prescription)

    if is_cpoe == False:
        query = (
            db.session.query(
                func.concat(
                    func.to_char(pr1.date, "DD/MM"),
                    " (",
                    pd1.frequency,
                    "x ",
                    func.trim(func.to_char(pd1.dose, "9G999G999D99")),
                    " ",
                    pd1.idMeasureUnit,
                    ")",
                )
            )
            .select_from(pd1)
            .join(pr1, pr1.id == pd1.idPrescription)
            .filter(pr1.admissionNumber == admissionNumber)
            .filter(pr1.id < idPrescription)
            .filter(pd1.idDrug == PrescriptionDrug.idDrug)
            .filter(pd1.suspendedDate == None)
            .filter(pr1.date > (date.today() - timedelta(days=30)))
            .order_by(asc(pr1.date))
            .as_scalar()
        )

        return func.array(query)
    else:
        sub_qry = (
            db.session.query(
                Prescription.date.label("date"),
                func.max(Prescription.expire).label("expire"),
                func.max(PrescriptionDrug.suspendedDate).label("suspension"),
                PrescriptionDrug.frequency.label("frequency"),
                PrescriptionDrug.dose.label("dose"),
                PrescriptionDrug.idMeasureUnit.label("idMeasureUnit"),
            )
            .select_from(PrescriptionDrug)
            .join(Prescription, Prescription.id == PrescriptionDrug.idPrescription)
            .filter(Prescription.admissionNumber == admissionNumber)
            .filter(PrescriptionDrug.idDrug == id_drug)
            .group_by(
                Prescription.date,
                PrescriptionDrug.frequency,
                PrescriptionDrug.dose,
                PrescriptionDrug.idMeasureUnit,
            )
            .order_by(asc(Prescription.date))
            .subquery()
        )

        cpoeperiods = db.aliased(sub_qry)

        query = db.session.query(
            func.concat(
                func.to_char(cpoeperiods.c.date, "DD/MM"),
                " - ",
                func.to_char(
                    func.coalesce(cpoeperiods.c.suspension, cpoeperiods.c.expire),
                    "DD/MM",
                ),
                " (",
                cpoeperiods.c.frequency,
                "x ",
                func.trim(func.to_char(cpoeperiods.c.dose, "9G999G999D99")),
                " ",
                cpoeperiods.c.idMeasureUnit,
                ")",
                case((cpoeperiods.c.suspension != None, " - suspenso"), else_=""),
            )
        ).select_from(cpoeperiods)

        return query


def getDrugFuture(idPrescription, admissionNumber):
    pd1 = db.aliased(PrescriptionDrug)
    pr1 = db.aliased(Prescription)

    query = (
        db.session.query(
            func.concat(
                pr1.id,
                " = ",
                func.to_char(pr1.date, "DD/MM"),
                " (",
                pd1.frequency,
                "x ",
                pd1.dose,
                " ",
                pd1.idMeasureUnit,
                ") via ",
                pd1.route,
                "; ",
            )
        )
        .select_from(pd1)
        .join(pr1, pr1.id == pd1.idPrescription)
        .filter(pr1.admissionNumber == admissionNumber)
        .filter(pr1.id > idPrescription)
        .filter(pd1.idDrug == PrescriptionDrug.idDrug)
        .filter(pd1.suspendedDate == None)
        .order_by(asc(pr1.date))
        .as_scalar()
    )

    return func.array(query)


def getPrevNotes(admissionNumber):
    prevNotes = db.aliased(Notes)
    prevUser = db.aliased(User)

    return (
        db.session.query(
            case(
                (
                    and_(prevNotes.notes != None, prevNotes.notes != ""),
                    func.concat(
                        prevNotes.notes,
                        " ##@",
                        prevUser.name,
                        " em ",
                        func.to_char(prevNotes.update, "DD/MM/YYYY HH24:MI"),
                        "@##",
                    ),
                ),
                else_=None,
            )
        )
        .select_from(prevNotes)
        .outerjoin(prevUser, prevNotes.user == prevUser.id)
        .filter(prevNotes.admissionNumber == admissionNumber)
        .filter(prevNotes.idDrug == PrescriptionDrug.idDrug)
        .filter(prevNotes.idPrescriptionDrug < PrescriptionDrug.id)
        .order_by(desc(prevNotes.update))
        .limit(1)
        .as_scalar()
    )


class PatientAudit(db.Model):
    __tablename__ = "pessoa_audit"

    id = db.Column("idpessoa_audit", db.BigInteger, nullable=False, primary_key=True)
    auditType = db.Column("tp_audit", db.Integer, nullable=False)
    admissionNumber = db.Column("nratendimento", db.BigInteger, nullable=False)
    extra = db.Column("extra", postgresql.JSON, nullable=True)
    createdAt = db.Column("created_at", db.DateTime, nullable=False)
    createdBy = db.Column("created_by", db.BigInteger, nullable=False)


class PrescriptionDrug(db.Model):
    __tablename__ = "presmed"

    id = db.Column("fkpresmed", db.BigInteger, primary_key=True)
    idOutlier = db.Column("idoutlier", db.BigInteger, nullable=False)
    idPrescription = db.Column("fkprescricao", db.BigInteger, nullable=False)
    idDrug = db.Column("fkmedicamento", db.BigInteger, nullable=False)
    idMeasureUnit = db.Column("fkunidademedida", db.String, nullable=False)
    idFrequency = db.Column("fkfrequencia", db.String, nullable=True)
    idSegment = db.Column("idsegmento", db.BigInteger, nullable=False)

    dose = db.Column("dose", db.Float, nullable=True)
    frequency = db.Column("frequenciadia", db.Float, nullable=True)
    doseconv = db.Column("doseconv", db.Float, nullable=True)
    route = db.Column("via", db.String, nullable=True)
    tube = db.Column("sonda", db.Boolean, nullable=True)
    intravenous = db.Column("intravenosa", db.Boolean, nullable=True)
    notes = db.Column("complemento", db.String, nullable=True)
    interval = db.Column("horario", db.String, nullable=True)
    source = db.Column("origem", db.String, nullable=True)
    allergy = db.Column("alergia", db.String(1), nullable=True)

    solutionGroup = db.Column("slagrupamento", db.String(1), nullable=True)
    solutionACM = db.Column("slacm", db.String(1), nullable=True)
    solutionPhase = db.Column("sletapas", db.String(1), nullable=True)
    solutionTime = db.Column("slhorafase", db.Float, nullable=True)
    solutionTotalTime = db.Column("sltempoaplicacao", db.String(1), nullable=True)
    solutionDose = db.Column("sldosagem", db.Float, nullable=True)
    solutionUnit = db.Column("sltipodosagem", db.String(3), nullable=True)

    status = db.Column("status", db.String(1), nullable=False)
    finalscore = db.Column("escorefinal", db.Integer, nullable=True)
    near = db.Column("aprox", db.Boolean, nullable=True)
    suspendedDate = db.Column("dtsuspensao", db.DateTime, nullable=True)
    checked = db.Column("checado", db.Boolean, nullable=True)
    period = db.Column("periodo", db.Integer, nullable=True)
    update = db.Column("update_at", db.DateTime, nullable=True)
    user = db.Column("update_by", db.BigInteger, nullable=True)

    cpoe_group = db.Column("cpoe_grupo", db.BigInteger, nullable=True)
    form = db.Column("form", postgresql.JSON, nullable=True)

    def findByPrescription(
        idPrescription,
        admissionNumber,
        aggDate=None,
        idSegment=None,
        is_cpoe=False,
        is_pmc=False,
    ):
        prevNotes = getPrevNotes(admissionNumber)

        if aggDate != None and is_cpoe:
            agg_date_with_time = cast(
                func.concat(func.date(aggDate), " ", "23:59:59"), postgresql.TIMESTAMP
            )

            period_calc = func.ceil(
                func.extract("epoch", agg_date_with_time - Prescription.date) / 86400
            )
            max_period = func.ceil(
                func.extract("epoch", Prescription.expire - Prescription.date) / 86400
            )
            period_cpoe = case(
                (agg_date_with_time > Prescription.expire, max_period),
                else_=period_calc,
            )

        else:
            period_cpoe = literal_column("0")

        substance_handling = (
            db.session.query(("*"))
            .select_from(func.jsonb_object_keys(Substance.handling))
            .filter(Substance.handling != None)
            .filter(Substance.handling != "null")
            .as_scalar()
        )

        q = (
            db.session.query(
                PrescriptionDrug,
                Drug,
                MeasureUnit,
                Frequency,
                literal("0"),
                func.coalesce(
                    PrescriptionDrug.finalscore,
                    func.coalesce(func.coalesce(Outlier.manualScore, Outlier.score), 4),
                ).label("score"),
                DrugAttributes,
                Notes.notes,
                prevNotes.label("prevNotes"),
                Prescription.status,
                Prescription.expire.label("prescription_expire"),
                Substance,
                period_cpoe.label("period_cpoe"),
                Prescription.date.label("prescription_date"),
                MeasureUnitConvert.factor.label("measure_unit_convert_factor"),
                func.array(substance_handling).label("substance_handling_types"),
            )
            .outerjoin(Outlier, Outlier.id == PrescriptionDrug.idOutlier)
            .outerjoin(Drug, Drug.id == PrescriptionDrug.idDrug)
            .outerjoin(Notes, Notes.idPrescriptionDrug == PrescriptionDrug.id)
            .outerjoin(Prescription, Prescription.id == PrescriptionDrug.idPrescription)
            .outerjoin(
                MeasureUnit,
                and_(
                    MeasureUnit.id == PrescriptionDrug.idMeasureUnit,
                    MeasureUnit.idHospital == Prescription.idHospital,
                ),
            )
            .outerjoin(
                MeasureUnitConvert,
                and_(
                    MeasureUnitConvert.idSegment == PrescriptionDrug.idSegment,
                    MeasureUnitConvert.idDrug == PrescriptionDrug.idDrug,
                    MeasureUnitConvert.idMeasureUnit == MeasureUnit.id,
                ),
            )
            .outerjoin(
                Frequency,
                and_(
                    Frequency.id == PrescriptionDrug.idFrequency,
                    Frequency.idHospital == Prescription.idHospital,
                ),
            )
            .outerjoin(
                DrugAttributes,
                and_(
                    DrugAttributes.idDrug == PrescriptionDrug.idDrug,
                    DrugAttributes.idSegment == PrescriptionDrug.idSegment,
                ),
            )
            .outerjoin(Substance, Drug.sctid == Substance.id)
        )

        if aggDate is None:
            q = q.filter(PrescriptionDrug.idPrescription == idPrescription)
        else:
            q = (
                q.filter(Prescription.admissionNumber == admissionNumber)
                .filter(Prescription.agg == None)
                .filter(Prescription.concilia == None)
            )

            q = get_period_filter(q, Prescription, aggDate, is_pmc, is_cpoe)

            if is_cpoe:
                q = q.filter(
                    or_(
                        PrescriptionDrug.suspendedDate == None,
                        func.date(PrescriptionDrug.suspendedDate) >= func.date(aggDate),
                    )
                )
            else:
                if idSegment != None:
                    q = q.filter(Prescription.idSegment == idSegment)

        return q.order_by(asc(Drug.name)).all()

    def findByPrescriptionDrug(idPrescriptionDrug, future, is_cpoe=False):
        pd = PrescriptionDrug.query.get(idPrescriptionDrug)
        if pd is None:
            return [{1: []}], None

        p = Prescription.query.get(pd.idPrescription)

        admissionHistory = None

        if future:
            drugHistory = getDrugFuture(p.id, p.admissionNumber)
            admissionHistory = Prescription.getFuturePrescription(
                p.id, p.admissionNumber
            )

            return (
                db.session.query(PrescriptionDrug, drugHistory.label("drugHistory"))
                .filter(PrescriptionDrug.id == idPrescriptionDrug)
                .all(),
                admissionHistory,
            )

        drugHistory = getDrugHistory(
            p.id, p.admissionNumber, id_drug=pd.idDrug, is_cpoe=is_cpoe
        )

        if is_cpoe:
            return drugHistory.all(), admissionHistory
        else:
            return (
                db.session.query(PrescriptionDrug, drugHistory.label("drugHistory"))
                .filter(PrescriptionDrug.id == idPrescriptionDrug)
                .all(),
                admissionHistory,
            )


class PrescriptionDrugAudit(db.Model):
    __tablename__ = "presmed_audit"

    id = db.Column("idpresmed_audit", db.BigInteger, nullable=False, primary_key=True)
    auditType = db.Column("tp_audit", db.Integer, nullable=False)
    idPrescriptionDrug = db.Column("fkpresmed", db.BigInteger, nullable=False)
    extra = db.Column("extra", postgresql.JSON, nullable=True)
    createdAt = db.Column("created_at", db.DateTime, nullable=False)
    createdBy = db.Column("created_by", db.BigInteger, nullable=False)


class Intervention(db.Model):
    __tablename__ = "intervencao"

    idIntervention = db.Column("idintervencao", db.BigInteger, primary_key=True)
    id = db.Column("fkpresmed", db.BigInteger, nullable=False)
    idPrescription = db.Column("fkprescricao", db.BigInteger, nullable=False)
    admissionNumber = db.Column("nratendimento", db.BigInteger, nullable=False)
    idInterventionReason = db.Column(
        "idmotivointervencao", postgresql.ARRAY(db.BigInteger), nullable=False
    )
    idDepartment = db.Column("fksetor", db.BigInteger, nullable=False)
    error = db.Column("erro", db.Boolean, nullable=True)
    cost = db.Column("custo", db.Boolean, nullable=True)
    notes = db.Column("observacao", db.String, nullable=True)
    interactions = db.Column(
        "interacoes", postgresql.ARRAY(db.BigInteger), nullable=True
    )
    date = db.Column("dtintervencao", db.DateTime, nullable=True)
    status = db.Column("status", db.String(1), nullable=True)
    update = db.Column("update_at", db.DateTime, nullable=False)
    user = db.Column("update_by", db.BigInteger, nullable=False)
    outcome_at = db.Column("outcome_at", db.DateTime, nullable=True)
    outcome_by = db.Column("outcome_by", db.BigInteger, nullable=True)
    transcription = db.Column("transcricao", postgresql.JSON, nullable=True)
    economy_days = db.Column("dias_economia", db.Integer, nullable=True)
    expended_dose = db.Column("dose_despendida", db.Float, nullable=True)
    economy_type = db.Column("tp_economia", db.Integer, nullable=True)
    economy_day_value = db.Column("vl_economia_dia", db.Float, nullable=True)
    economy_day_value_manual = db.Column(
        "vl_economia_dia_manual", db.Boolean, nullable=False
    )
    idPrescriptionDrugDestiny = db.Column(
        "fkpresmed_destino", db.BigInteger, nullable=True
    )
    date_base_economy = db.Column("dt_base_economia", db.DateTime, nullable=True)
    date_end_economy = db.Column("dt_fim_economia", db.DateTime, nullable=True)

    origin = db.Column("origem", postgresql.JSONB, nullable=True)
    destiny = db.Column("destino", postgresql.JSONB, nullable=True)
