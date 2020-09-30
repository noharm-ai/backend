from .main import *
from .appendix import *
from .segment import *
from routes.utils import *
from datetime import datetime
from sqlalchemy.orm import deferred
from sqlalchemy import case

class Prescription(db.Model):
    __tablename__ = 'prescricao'

    id = db.Column("fkprescricao", db.Integer, primary_key=True)
    idPatient = db.Column("fkpessoa", db.Integer, nullable=False)
    admissionNumber = db.Column('nratendimento', db.Integer, nullable=True)
    idHospital = db.Column("fkhospital", db.Integer, nullable=False)
    idDepartment = db.Column("fksetor", db.Integer, nullable=False)
    idSegment = db.Column("idsegmento", db.Integer, nullable=False)
    date = db.Column("dtprescricao", db.DateTime, nullable=False)
    expire = db.Column("dtvigencia", db.DateTime, nullable=True)
    status = db.Column('status', db.String(1), nullable=False)
    bed = db.Column('leito', db.String(16), nullable=True)
    record = db.Column('prontuario', db.Integer, nullable=True)
    features = db.Column('indicadores', postgresql.JSON, nullable=True)
    notes = deferred(db.Column('evolucao', db.String, nullable=True))
    notes_at = db.Column('evolucao_at', db.DateTime, nullable=True)
    prescriber = deferred(db.Column('prescritor', db.String, nullable=True))
    agg = db.Column('agregada', db.Boolean, nullable=True)
    update = db.Column("update_at", db.DateTime, nullable=True)
    user = db.Column("update_by", db.Integer, nullable=True)

    def getFuturePrescription(idPrescription, admissionNumber):
        return db.session.query(Prescription)\
            .filter(Prescription.admissionNumber == admissionNumber)\
            .filter(Prescription.id > idPrescription)\
            .first()

    def lastDeptbyAdmission(idPrescription, admissionNumber):
        return db.session.query(Department.name)\
            .select_from(Prescription)\
            .outerjoin(Department, Department.id == Prescription.idDepartment)\
            .filter(Prescription.admissionNumber == admissionNumber)\
            .filter(Prescription.id < idPrescription)\
            .order_by(desc(Prescription.date))\
            .first()

    def getPrescriptionBasic():
            return db.session\
            .query(
                Prescription, Patient, '0', '0',
                Department.name.label('department'), Segment.description, 
                Patient.observation, Prescription.notes, Patient.alert,
                Prescription.prescriber
            )\
            .outerjoin(Patient, Patient.admissionNumber == Prescription.admissionNumber)\
            .outerjoin(Department, Department.id == Prescription.idDepartment)\
            .outerjoin(Segment, Segment.id == Prescription.idSegment)

    def getPrescription(idPrescription):
        return Prescription.getPrescriptionBasic()\
            .filter(Prescription.id == idPrescription)\
            .first()

    def getPrescriptionAgg(admissionNumber, aggDate):
        return Prescription.getPrescriptionBasic()\
            .filter(Prescription.admissionNumber == admissionNumber)\
            .filter(or_(
                func.date(Prescription.date) == aggDate,
                func.date(Prescription.expire) == aggDate
            ))\
            .order_by(desc(Prescription.date))\
            .first()

    def shouldUpdate(idPrescription):
        return db.session\
            .query(DrugAttributes.update)\
            .select_from(PrescriptionDrug)\
            .join(DrugAttributes, and_(DrugAttributes.idDrug == PrescriptionDrug.idDrug, DrugAttributes.idSegment == PrescriptionDrug.idSegment))\
            .join(Outlier, Outlier.id == PrescriptionDrug.idOutlier)\
            .filter(PrescriptionDrug.idPrescription == idPrescription)\
            .filter(or_(
                        DrugAttributes.update > (datetime.today() - timedelta(minutes=3)),
                        Outlier.update > (datetime.today() - timedelta(minutes=3))
                    ))\
            .all()

    def getHeaders(admissionNumber, aggDate):
        prescriptions = db.session.query(Prescription)\
                    .filter(Prescription.admissionNumber == admissionNumber)\
                    .filter(or_(
                                func.date(Prescription.date) == aggDate,
                                func.date(Prescription.expire) == aggDate
                            ))\
                    .filter(Prescription.agg == None)\
                    .all()
        headers = {}
        for p in prescriptions:
            headers[p.id] = {
                'date': p.date.isoformat() if p.date else None,
                'expire': p.expire.isoformat() if p.expire else None,
                'status': p.status,
                'bed': p.bed,
                'prescriber': p.prescriber
            }

        return headers

    def findRelation(idPrescription, admissionNumber, aggDate=None):
        pd1 = db.aliased(PrescriptionDrug)
        pd2 = db.aliased(PrescriptionDrug)
        m1 = db.aliased(Drug)
        m2 = db.aliased(Drug)

        relation = db.session\
            .query(pd1.id, Relation, m1.name, m2.name)\
            .join(pd2, and_(pd2.idPrescription == pd1.idPrescription, pd2.id != pd1.id))\
            .join(m1, m1.id == pd1.idDrug)\
            .join(m2, m2.id == pd2.idDrug)\
            .join(Relation, and_(Relation.sctida == m1.sctid, Relation.sctidb == m2.sctid))\
            .filter(Relation.active == True)
        
        if aggDate is None:
            relation = relation.filter(pd1.idPrescription == idPrescription)
        else:
            relation = relation.outerjoin(Prescription, Prescription.id == pd1.idPrescription)\
                               .filter(Prescription.admissionNumber == admissionNumber)\
                               .filter(or_(
                                    func.date(Prescription.date) == aggDate,
                                    func.date(Prescription.expire) == aggDate
                                ))

        interaction = relation.filter(Relation.kind.in_(['it','dt','dm']))

        incompatible = relation.filter(Relation.kind.in_(['iy']))\
                        .filter(pd1.route.in_(['Intravenosa infusao','Infusão Contínua','IV']))\
                        .filter(pd2.route.in_(['Intravenosa infusao','Infusão Contínua','IV']))

        admissionAlergy = db.session.query(PrescriptionDrug.idDrug.label('idDrug'), func.min(PrescriptionDrug.id).label('id') )\
                      .select_from(PrescriptionDrug)\
                      .join(Prescription, Prescription.id == PrescriptionDrug.idPrescription)\
                      .filter(Prescription.admissionNumber == admissionNumber)\
                      .filter(PrescriptionDrug.alergy == 'S')\
                      .group_by(PrescriptionDrug.idDrug)\
                      .subquery()

        al = db.aliased(admissionAlergy)

        xreactivity = db.session\
            .query(pd1.id, Relation, m1.name, m2.name)\
            .join(al, al.c.id != pd1.id)\
            .join(m1, m1.id == pd1.idDrug)\
            .join(m2, m2.id == al.c.idDrug)\
            .join(Relation, or_(
                                and_(Relation.sctida == m1.sctid, Relation.sctidb == m2.sctid),
                                and_(Relation.sctida == m2.sctid, Relation.sctidb == m1.sctid),
                            ))\
            .filter(Relation.active == True)\
            .filter(Relation.kind.in_(['rx']))

        if aggDate is None:
            xreactivity = xreactivity.filter(pd1.idPrescription == idPrescription)
        else:
            xreactivity = xreactivity.outerjoin(Prescription, Prescription.id == pd1.idPrescription)\
                               .filter(Prescription.admissionNumber == admissionNumber)\
                               .filter(or_(
                                    func.date(Prescription.date) == aggDate,
                                    func.date(Prescription.expire) == aggDate
                                ))

        relations = interaction.union(incompatible).union(xreactivity).all()

        results = {}
        pairs = []
        for r in relations:
            key = str(r[1].sctida) + '-' + str(r[1].sctidb)
            if key in pairs: 
                continue;

            alert = typeRelations[r[1].kind] + ': '
            alert += strNone(r[1].text) + ' (' + strNone(r[2]) + ' e ' + strNone(r[3]) + ')'

            if r[0] in results: 
                results[r[0]].append(alert)
            else:
                results[r[0]] = [alert]

            if (r[1].sctida == r[1].sctidb): 
                pairs.append(key)

        return results

def getDrugList():
    query = db.session.query(cast(PrescriptionDrug.idDrug,db.Integer))\
        .select_from(PrescriptionDrug)\
        .filter(PrescriptionDrug.idPrescription == Prescription.id)\
        .as_scalar()

    return func.array(query)

class Patient(db.Model):
    __tablename__ = 'pessoa'

    idPatient = db.Column("fkpessoa", db.Integer, nullable=False)
    fkHospital = db.Column("fkhospital", db.Integer, nullable=False)
    admissionNumber = db.Column('nratendimento', db.Integer, primary_key=True)
    admissionDate = db.Column('dtinternacao', db.DateTime, nullable=True)
    birthdate = db.Column('dtnascimento', db.DateTime, nullable=True)
    gender = db.Column('sexo', db.String(1), nullable=True)
    weight = db.Column('peso', db.Float, nullable=True)
    height = db.Column('altura', db.Float, nullable=True)
    weightDate = db.Column('dtpeso', db.DateTime, nullable=True)
    observation = deferred(db.Column('anotacao', db.String, nullable=True))
    skinColor = db.Column('cor', db.String, nullable=True)
    update = db.Column("update_at", db.DateTime, nullable=True)
    user = db.Column("update_by", db.Integer, nullable=True)
    alert = deferred(db.Column('alertatexto', db.String, nullable=True))
    alertDate = db.Column("alertadata", db.DateTime, nullable=True)
    alertExpire = db.Column("alertavigencia", db.DateTime, nullable=True)
    alertBy = db.Column("alerta_by", db.Integer, nullable=True)
    dischargeReason = db.Column('motivoalta', db.String, nullable=True)
    dischargeDate = db.Column("dtalta", db.DateTime, nullable=True)

    def findByAdmission(admissionNumber):
        return db.session.query(Patient)\
                         .filter(Patient.admissionNumber == admissionNumber)\
                         .first()

    def getPatients(idSegment=None, idDept=[], idDrug=[], startDate=date.today(), endDate=None, pending=False, agg=False):
        q = db.session\
            .query(Prescription, Patient, Department.name.label('department'))\
            .outerjoin(Patient, Patient.admissionNumber == Prescription.admissionNumber)\
            .outerjoin(Department, Department.id == Prescription.idDepartment)

        if (not(idSegment is None)):
            q = q.filter(Prescription.idSegment == idSegment)

        if (len(idDept)>0):
            q = q.filter(Prescription.idDepartment.in_(idDept))

        if (len(idDrug)>0):
            drugList = getDrugList()
            idDrug = list(map(int, idDrug))
            q = q.filter(postgresql.array(idDrug).overlap(drugList))

        if bool(int(none2zero(pending))):
            q = q.filter(Prescription.status == '0')

        if bool(int(none2zero(agg))):
            q = q.filter(Prescription.agg == True)
        else:
            q = q.filter(Prescription.agg == None)

        if endDate is None: endDate = startDate

        q = q.filter(func.date(Prescription.date) >= validate(startDate))
        q = q.filter(func.date(Prescription.date) <= validate(endDate))

        q = q.order_by(desc(Prescription.date))

        return q.limit(500).all()

def getDrugHistory(idPrescription, admissionNumber):
    pd1 = db.aliased(PrescriptionDrug)
    pr1 = db.aliased(Prescription)

    query = db.session.query(func.concat(func.to_char(pr1.date, "DD/MM"),' (',pd1.frequency,'x ',pd1.dose,' ',pd1.idMeasureUnit,')'))\
        .select_from(pd1)\
        .join(pr1, pr1.id == pd1.idPrescription)\
        .filter(pr1.admissionNumber == admissionNumber)\
        .filter(pr1.id < idPrescription)\
        .filter(pd1.idDrug == PrescriptionDrug.idDrug)\
        .filter(pd1.suspendedDate == None)\
        .filter(pr1.date > (date.today() - timedelta(days=30)))\
        .order_by(asc(pr1.date))\
        .as_scalar()

    return func.array(query)

def getDrugFuture(idPrescription, admissionNumber):
    pd1 = db.aliased(PrescriptionDrug)
    pr1 = db.aliased(Prescription)

    query = db.session.query(func.concat(pr1.id,' = ',func.to_char(pr1.date, "DD/MM"),' (',pd1.frequency,'x ',pd1.dose,' ',pd1.idMeasureUnit,') via ',pd1.route,'; '))\
        .select_from(pd1)\
        .join(pr1, pr1.id == pd1.idPrescription)\
        .filter(pr1.admissionNumber == admissionNumber)\
        .filter(pr1.id > idPrescription)\
        .filter(pd1.idDrug == PrescriptionDrug.idDrug)\
        .filter(pd1.suspendedDate == None)\
        .order_by(asc(pr1.date))\
        .as_scalar()

    return func.array(query)

def getPrevNotes(admissionNumber):
    prevNotes = db.aliased(Notes)

    return db.session.query(prevNotes.notes)\
            .select_from(prevNotes)\
            .filter(prevNotes.admissionNumber == admissionNumber)\
            .filter(prevNotes.idDrug == PrescriptionDrug.idDrug)\
            .filter(prevNotes.idPrescriptionDrug < PrescriptionDrug.id)\
            .order_by(desc(prevNotes.update))\
            .limit(1)\
            .as_scalar()

class PrescriptionDrug(db.Model):
    __tablename__ = 'presmed'

    id = db.Column("fkpresmed", db.Integer, primary_key=True)
    idOutlier = db.Column("idoutlier", db.Integer, nullable=False)
    idPrescription = db.Column("fkprescricao", db.Integer, nullable=False)
    idDrug = db.Column("fkmedicamento", db.Integer, nullable=False)
    idMeasureUnit = db.Column("fkunidademedida", db.String, nullable=False)
    idFrequency = db.Column("fkfrequencia", db.String, nullable=True)
    idSegment = db.Column("idsegmento", db.Integer, nullable=False)

    dose = db.Column("dose", db.Float, nullable=True)
    frequency = db.Column("frequenciadia", db.Float, nullable=True)
    doseconv = db.Column("doseconv", db.Float, nullable=True)
    route = db.Column('via', db.String, nullable=True)
    notes = db.Column('complemento', db.String, nullable=True)
    interval = db.Column('horario', db.String, nullable=True)
    source = db.Column('origem', db.String, nullable=True)
    default = db.Column('padronizado', db.String(1), nullable=True)
    alergy = db.Column('alergia', db.String(1), nullable=True)

    solutionGroup = db.Column('slagrupamento', db.String(1), nullable=True)
    solutionACM = db.Column('slacm', db.String(1), nullable=True)
    solutionPhase = db.Column('sletapas', db.String(1), nullable=True)
    solutionTime = db.Column('slhorafase', db.Float, nullable=True)
    solutionTotalTime = db.Column('sltempoaplicacao', db.String(1), nullable=True)
    solutionDose = db.Column('sldosagem', db.Float, nullable=True)
    solutionUnit = db.Column('sltipodosagem', db.String(3), nullable=True)

    status = db.Column('status', db.String(1), nullable=False)
    finalscore = db.Column('escorefinal', db.Integer, nullable=True)
    near = db.Column("aprox", db.Boolean, nullable=True)
    suspendedDate = db.Column("dtsuspensao", db.DateTime, nullable=True)
    checked = db.Column("checado", db.Boolean, nullable=True)
    period = db.Column("periodo", db.Integer, nullable=True)
    update = db.Column("update_at", db.DateTime, nullable=True)
    user = db.Column("update_by", db.Integer, nullable=True)

    def findByPrescription(idPrescription, admissionNumber, aggDate=None):
        prevNotes = getPrevNotes(admissionNumber)

        q = db.session\
            .query(PrescriptionDrug, Drug, MeasureUnit, Frequency, '0',\
                    func.coalesce(func.coalesce(Outlier.manualScore, Outlier.score), 4).label('score'),
                    DrugAttributes, Notes.notes, prevNotes.label('prevNotes'), Prescription.status,
                    func.concat(PrescriptionDrug.idPrescription,PrescriptionDrug.solutionGroup))\
            .outerjoin(Outlier, Outlier.id == PrescriptionDrug.idOutlier)\
            .outerjoin(Drug, Drug.id == PrescriptionDrug.idDrug)\
            .outerjoin(Notes, Notes.idPrescriptionDrug == PrescriptionDrug.id)\
            .outerjoin(MeasureUnit, MeasureUnit.id == PrescriptionDrug.idMeasureUnit)\
            .outerjoin(Frequency, Frequency.id == PrescriptionDrug.idFrequency)\
            .outerjoin(DrugAttributes, and_(DrugAttributes.idDrug == PrescriptionDrug.idDrug, DrugAttributes.idSegment == PrescriptionDrug.idSegment))\
            .outerjoin(Prescription, Prescription.id == PrescriptionDrug.idPrescription)\
        
        if aggDate is None:
            q = q.filter(PrescriptionDrug.idPrescription == idPrescription)
        else:
            q = q.filter(Prescription.admissionNumber == admissionNumber)\
                 .filter(or_(
                            func.date(Prescription.date) == aggDate,
                            func.date(Prescription.expire) == aggDate
                         ))\
                 .filter(Prescription.agg == None)
        
        return q.order_by(asc(Prescription.expire), desc(func.concat(PrescriptionDrug.idPrescription,PrescriptionDrug.solutionGroup)), asc(Drug.name)).all()

    def findByPrescriptionDrug(idPrescriptionDrug, future):
        pd = PrescriptionDrug.query.get(idPrescriptionDrug)
        p = Prescription.query.get(pd.idPrescription)

        admissionHistory = None
        if future:
            drugHistory = getDrugFuture(p.id, p.admissionNumber)
            admissionHistory = Prescription.getFuturePrescription(p.id, p.admissionNumber)
        else:
            drugHistory = getDrugHistory(p.id, p.admissionNumber)

        return db.session\
            .query(PrescriptionDrug, drugHistory.label('drugHistory'))\
            .filter(PrescriptionDrug.id == idPrescriptionDrug)\
            .all() , admissionHistory

class Intervention(db.Model):
    __tablename__ = 'intervencao'

    id = db.Column("fkpresmed", db.Integer, primary_key=True)
    admissionNumber = db.Column('nratendimento', db.Integer, nullable=False)
    idInterventionReason = db.Column("idmotivointervencao", db.Integer, nullable=False)
    error = db.Column('erro', db.Boolean, nullable=True)
    cost = db.Column("custo", db.Boolean, nullable=True)
    notes = db.Column("observacao", db.String, nullable=True)
    interactions = db.Column('interacoes', postgresql.ARRAY(db.Integer), nullable=True)
    date = db.Column("dtintervencao", db.DateTime, nullable=True)
    status = db.Column('status', db.String(1), nullable=True)
    update = db.Column("update_at", db.DateTime, nullable=False)
    user = db.Column("update_by", db.Integer, nullable=False)

    def findAll(admissionNumber=None,userId=None):
        mReasion = db.aliased(InterventionReason)
        descript = case([(
                            mReasion.description != None,
                            func.concat(mReasion.description, ' - ',InterventionReason.description)
                        ),],
                        else_=InterventionReason.description)

        reason = db.session.query(descript)\
                .select_from(InterventionReason)\
                .outerjoin(mReasion, mReasion.id == InterventionReason.mamy)\
                .filter(InterventionReason.id == func.any(Intervention.idInterventionReason))\
                .as_scalar()

        splitStr = '!?'
        dr1 = db.aliased(Drug)
        interactions = db.session.query(func.concat(dr1.name, splitStr, dr1.id))\
                .select_from(dr1)\
                .filter(dr1.id == func.any(Intervention.interactions))\
                .as_scalar()

        interventions = db.session\
            .query(Intervention, PrescriptionDrug, 
                    func.array(reason).label('reason'), Drug.name, 
                    func.array(interactions).label('interactions'),
                    MeasureUnit, Frequency)\
            .join(PrescriptionDrug, Intervention.id == PrescriptionDrug.id)\
            .outerjoin(Drug, Drug.id == PrescriptionDrug.idDrug)\
            .outerjoin(MeasureUnit, MeasureUnit.id == PrescriptionDrug.idMeasureUnit)\
            .outerjoin(Frequency, Frequency.id == PrescriptionDrug.idFrequency)

        if admissionNumber:
            interventions = interventions.filter(Intervention.admissionNumber == admissionNumber)
        if userId:
            interventions = interventions.filter(Intervention.user == userId)

        interventions = interventions.filter(Intervention.status.in_(['s','a','n','x']))\
                                     .order_by(desc(Intervention.date)).all()

        intervBuffer = []
        for i in interventions:
            intervBuffer.append({
                'id': i[0].id,
                'idSegment': i[1].idSegment,
                'idInterventionReason': i[0].idInterventionReason,
                'reasonDescription': (', ').join(i[2]),
                'idPrescription': i[1].idPrescription,
                'idDrug': i[1].idDrug,
                'drugName': i[3] if i[3] is not None else 'Medicamento ' + str(i[1].idDrug),
                'dose': i[1].dose,
                'measureUnit': { 'value': i[5].id, 'label': i[5].description } if i[5] else '',
                'frequency': { 'value': i[6].id, 'label': i[6].description } if i[6] else '',
                'time': timeValue(i[1].interval),
                'route': i[1].route,
                'admissionNumber': i[0].admissionNumber,
                'observation': i[0].notes,
                'error': i[0].error,
                'cost': i[0].cost,
                'interactionsDescription': (', ').join([ d.split(splitStr)[0] for d in i[4] ] ),
                'interactionsList': interactionsList(i[4], splitStr),
                'interactions': i[0].interactions,
                'date': i[0].date.isoformat(),
                'status': i[0].status
            })

        result = [i for i in intervBuffer if i['status'] == 's']
        result.extend([i for i in intervBuffer if i['status'] != 's'])

        return result