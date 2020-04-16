from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, text, and_, or_, desc, asc, distinct
from datetime import date, timedelta
from sqlalchemy.dialects import postgresql

db = SQLAlchemy()

def setSchema(schema):
    Prescription.setSchema(schema)
    Patient.setSchema(schema)
    InterventionReason.setSchema(schema)
    PrescriptionDrug.setSchema(schema)
    Outlier.setSchema(schema)
    Drug.setSchema(schema)
    MeasureUnit.setSchema(schema)
    Frequency.setSchema(schema)
    Segment.setSchema(schema)
    Department.setSchema(schema)
    Intervention.setSchema(schema)
    SegmentDepartment.setSchema(schema)
    Exams.setSchema(schema)
    PrescriptionAgg.setSchema(schema)
    MeasureUnitConvert.setSchema(schema)
    PrescriptionPic.setSchema(schema)
    OutlierObs.setSchema(schema)


class User(db.Model):
    __tablename__ = 'usuario'

    id = db.Column("idusuario", db.Integer, primary_key=True)
    name = db.Column('nome', db.String(250), nullable=False)
    email = db.Column("email", db.String(254), unique=True, nullable=False)
    password = db.Column('senha', db.String(128), nullable=False)
    schema = db.Column("schema", db.String, nullable=False)
    nameUrl = db.Column("getnameurl", db.String, nullable=False)
    logourl = db.Column("logourl", db.String, nullable=False)

    def find(id):
        return User.query.filter(User.id == id).first()

    def authenticate(email, password):
        return User.query.filter_by(email=email, password=password).first()


class Prescription(db.Model):
    __tablename__ = 'prescricao'

    id = db.Column("fkprescricao", db.Integer, primary_key=True)
    idPatient = db.Column("fkpessoa", db.Integer, nullable=False)
    admissionNumber = db.Column('nratendimento', db.Integer, nullable=True)
    idHospital = db.Column("fkhospital", db.Integer, nullable=False)
    idDepartment = db.Column("fksetor", db.Integer, nullable=False)
    idSegment = db.Column("idsegmento", db.Integer, nullable=False)
    date = db.Column("dtprescricao", db.DateTime, nullable=False)
    status = db.Column('status', db.String(1), nullable=False)
    update = db.Column("update_at", db.DateTime, nullable=True)
    user = db.Column("update_by", db.Integer, nullable=True)

    def setSchema(schema):
        Prescription.__table__.schema = schema

    def getPrescription(idPrescription):
        score = getAggScore()

        return db.session\
            .query(
                Prescription, Patient,
                func.trunc((func.extract('epoch', func.current_date(
                )) - func.extract('epoch', Prescription.date)) / 86400).label('daysAgo'), score,
                Department.name.label('department')
            )\
            .outerjoin(Patient, Patient.admissionNumber == Prescription.admissionNumber)\
            .outerjoin(Department, Department.id == Prescription.idDepartment)\
            .filter(Prescription.id == idPrescription)\
            .first()

def getAggScore():
    return db.session.query(func.sum(func.coalesce(func.coalesce(Outlier.manualScore, Outlier.score), 4)).label('score'))\
        .select_from(PrescriptionDrug)\
        .outerjoin(Outlier, and_(Outlier.id == PrescriptionDrug.idOutlier))\
        .filter(PrescriptionDrug.idPrescription == Prescription.id)\
        .as_scalar()

def getScore(level):
    return db.session.query(func.count(func.coalesce(func.coalesce(Outlier.manualScore, Outlier.score), 4)).label('scoreOne'))\
        .select_from(PrescriptionDrug)\
        .outerjoin(Outlier, and_(Outlier.id == PrescriptionDrug.idOutlier))\
        .filter(PrescriptionDrug.idPrescription == Prescription.id)\
        .filter(func.coalesce(Outlier.manualScore, Outlier.score) == level)\
        .as_scalar()

def getHighScore():
    return db.session.query(func.count(func.coalesce(func.coalesce(Outlier.manualScore, Outlier.score), 4)).label('scoreOne'))\
        .select_from(PrescriptionDrug)\
        .outerjoin(Outlier, and_(Outlier.id == PrescriptionDrug.idOutlier))\
        .filter(PrescriptionDrug.idPrescription == Prescription.id)\
        .filter(or_(func.coalesce(Outlier.manualScore, Outlier.score) == 3, func.coalesce(Outlier.manualScore, Outlier.score) == None))\
        .as_scalar()

def getExams(typeExam):
    return db.session.query(Exams.value)\
        .select_from(Exams)\
        .filter(Exams.idPatient == Prescription.idPatient)\
        .filter(Exams.typeExam == typeExam)\
        .order_by(Exams.date.desc()).limit(1)\
        .as_scalar()

def getDrugClass(typeClass):
    return db.session.query(func.count(1).label('drugClass'))\
        .select_from(Drug)\
        .outerjoin(PrescriptionDrug, and_(Drug.id == PrescriptionDrug.idDrug))\
        .filter(PrescriptionDrug.idPrescription == Prescription.id)\
        .filter(typeClass == True)\
        .as_scalar()

def getDrugRoute(route):
    return db.session.query(func.count(1).label('drugRoute'))\
        .select_from(PrescriptionDrug)\
        .filter(PrescriptionDrug.idPrescription == Prescription.id)\
        .filter(PrescriptionDrug.route.ilike(route))\
        .as_scalar()

def getDrugsCount():
    return db.session.query(func.count(1).label('drugCount'))\
        .select_from(PrescriptionDrug, Prescription)\
        .filter(PrescriptionDrug.idPrescription == Prescription.id)\
        .as_scalar()   

def getDrugDiff():
    pd2 = db.aliased(PrescriptionDrug)
    pd1 = db.aliased(PrescriptionDrug)
    pr1 = db.aliased(Prescription)

    return db.session.query(func.count(distinct(func.concat(pd2.idDrug, pd2.dose, pd2.idFrequency))).label('drugDiff'))\
        .select_from(pd2)\
        .outerjoin(pd1, and_(pd1.idDrug == pd2.idDrug, pd1.dose == pd2.dose, pd1.idFrequency == pd2.idFrequency))\
        .join(pr1, pr1.id == pd1.idPrescription)\
        .filter(pd2.idPrescription == Prescription.id)\
        .filter(pr1.idPatient == Patient.id)\
        .filter(pr1.status == 's')\
        .filter(pr1.id < Prescription.id)\
        .as_scalar() 

class Patient(db.Model):
    __tablename__ = 'pessoa'

    id = db.Column("fkpessoa", db.Integer, primary_key=True)
    fkHospital = db.Column("fkhospital", db.Integer, nullable=False)
    admissionNumber = db.Column('nratendimento', db.Integer, nullable=False)
    birthdate = db.Column('dtnascimento', db.DateTime, nullable=True)
    gender = db.Column('sexo', db.String(1), nullable=True)
    weight = db.Column('peso', db.Integer, nullable=True)
    skinColor = db.Column('cor', db.String, nullable=True)

    def setSchema(schema):
        Patient.__table__.schema = schema

    def getPatients(idSegment=None, idDept=None, idPrescription=None, limit=200, onlyStatus=False):
        score = getAggScore()
        scoreOne = getScore(1)
        scoreTwo = getScore(2)
        scoreThree = getHighScore()
        tgo = getExams('TGO')
        tgp = getExams('TGP')
        cr = getExams('CR')
        k = getExams('K')
        na = getExams('NA')
        mg = getExams('MG')
        rni = getExams('PRO')
        antimicro = getDrugClass(Drug.antimicro)
        mav = getDrugClass(Drug.mav)
        controlled = getDrugClass(Drug.controlled)
        notdefault = getDrugClass(Drug.notdefault)
        sonda = getDrugRoute("%sonda%")
        diff = getDrugDiff()
        count = getDrugsCount()

        if onlyStatus:
            q = db.session.query(Prescription)
        else:
            q = db.session\
                .query(
                    Prescription, Patient,
                    func.trunc((func.extract('epoch', func.current_date(
                    )) - func.extract('epoch', Prescription.date)) / 86400).label('daysAgo'),
                    score.label('score'), scoreOne.label('scoreOne'), scoreTwo.label('scoreTwo'), scoreThree.label('scoreThree'),
                    tgo.label('tgo'), tgp.label('tgp'), cr.label('cr'), k.label('k'), na.label('na'), mg.label('mg'), rni.label('rni'),
                    antimicro.label('antimicro'), mav.label('mav'), controlled.label('controlled'), sonda.label('sonda'),
                    (count - diff).label('diff'), Department.name.label('department'), controlled.label('notdefault')
                )\
                .outerjoin(Patient, Patient.admissionNumber == Prescription.admissionNumber)\
                .outerjoin(Department, Department.id == Prescription.idDepartment)

        if (not(idSegment is None)):
            q = q.filter(Prescription.idSegment == idSegment)

        if (not(idDept is None)):
            q = q.filter(Prescription.idDepartment == idDept)

        if (not(idPrescription is None)):
            q = q.filter(Prescription.id == idPrescription)

        q = q.filter(Prescription.date > (date.today() - timedelta(days=1)))

        if onlyStatus:
            wrapper = q
        else:
            q = q.with_labels().subquery()

            prescritionAlias = db.aliased(Prescription, q)
            patientAlias = db.aliased(Patient, q)

            wrapper = db.session\
                .query(prescritionAlias, patientAlias,\
                        '"daysAgo"', 'score', '"scoreOne"', '"scoreTwo"', '"scoreThree"',\
                        'tgo', 'tgp', 'cr', 'k', 'na', 'mg', 'rni',\
                        'antimicro', 'mav', 'controlled', 'sonda', 'diff', 'department', 'notdefault')

            wrapper = wrapper.order_by(desc(prescritionAlias.date))


        return wrapper.limit(limit).all()


class Outlier(db.Model):
    __tablename__ = 'outlier'

    id = db.Column("idoutlier", db.Integer, primary_key=True)
    idDrug = db.Column("fkmedicamento", db.Integer, nullable=False)
    idSegment = db.Column("idsegmento", db.Integer, nullable=False)
    countNum = db.Column("contagem", db.Integer, nullable=True)
    dose = db.Column("doseconv", db.Float, nullable=True)
    frequency = db.Column("frequenciadia", db.Float, nullable=True)
    score = db.Column("escore", db.Integer, nullable=True)
    manualScore = db.Column("escoremanual", db.Integer, nullable=True)
    update = db.Column("update_at", db.DateTime, nullable=True)
    user = db.Column("update_by", db.Integer, nullable=True)

    def setSchema(schema):
        Outlier.__table__.schema = schema


class OutlierObs(db.Model):
    __tablename__ = 'outlierobs'

    id = db.Column("idoutlier", db.Integer, primary_key=True)
    idSegment = db.Column("idsegmento", db.Integer, nullable=False)
    idDrug = db.Column("fkmedicamento", db.Integer, nullable=False)
    dose = db.Column("doseconv", db.Float, nullable=True)
    frequency = db.Column("frequenciadia", db.Float, nullable=True)
    notes = db.Column('text', db.String, nullable=True)
    update = db.Column("update_at", db.DateTime, nullable=True)
    user = db.Column("update_by", db.Integer, nullable=True)

    def setSchema(schema):
        OutlierObs.__table__.schema = schema

class PrescriptionAgg(db.Model):
    __tablename__ = 'prescricaoagg'

    idHospital = db.Column("fkhospital", db.Integer, nullable=False)
    idDepartment = db.Column("fksetor", db.Integer, primary_key=True)
    idSegment = db.Column("idsegmento", db.Integer, nullable=False)
    idDrug = db.Column("fkmedicamento", db.Integer, primary_key=True)
    idMeasureUnit = db.Column("fkunidademedida", db.Integer, nullable=False)
    idFrequency = db.Column("fkfrequencia", db.String, primary_key=True)
    dose = db.Column("dose", db.Float, primary_key=True)
    doseconv = db.Column("doseconv", db.Float, nullable=True)
    frequency = db.Column("frequenciadia", db.Float, nullable=True)
    countNum = db.Column("contagem", db.Integer, nullable=True)

    def setSchema(schema):
        PrescriptionAgg.__table__.schema = schema

def getDrugHistory(idPrescription, admissionNumber):
    pd1 = db.aliased(PrescriptionDrug)
    pr1 = db.aliased(Prescription)
    
    query = db.session.query(func.DATE(pr1.date).distinct())\
        .select_from(pd1)\
        .join(pr1, pr1.id == pd1.idPrescription)\
        .filter(pr1.admissionNumber == admissionNumber)\
        .filter(pr1.id < idPrescription)\
        .filter(pd1.idDrug == PrescriptionDrug.idDrug)\
        .order_by(asc(func.DATE(pr1.date)))\
        .as_scalar()

    return db.session.query(func.array(query))

def getDrugOption(idPrescription, idPatient, option):
    pd1 = db.aliased(PrescriptionDrug)
    pr1 = db.aliased(Prescription)
    
    query = db.session.query(func.count(distinct(func.concat(pd1.idDrug, pd1.doseconv, pd1.frequency))).label('checked'))\
        .select_from(pd1)\
        .join(pr1, pr1.id == pd1.idPrescription)\
        .filter(pr1.idPatient == idPatient)\
        .filter(pr1.id < idPrescription)\
        .filter(pd1.idDrug == PrescriptionDrug.idDrug)\
        .filter(pd1.doseconv == PrescriptionDrug.doseconv)\
        .filter(pd1.frequency == PrescriptionDrug.frequency)\

    if option == 'checked':
        query = query.filter(pr1.status == 's')
    else:
        query = query.filter(pd1.status == 's')

    return query.as_scalar() 

class PrescriptionDrug(db.Model):
    __tablename__ = 'presmed'

    id = db.Column("fkpresmed", db.Integer, primary_key=True)
    idOutlier = db.Column("idoutlier", db.Integer, nullable=False)
    idPrescription = db.Column("fkprescricao", db.Integer, nullable=False)
    idDrug = db.Column("fkmedicamento", db.Integer, nullable=False)
    idMeasureUnit = db.Column("fkunidademedida", db.Integer, nullable=False)
    idFrequency = db.Column("fkfrequencia", db.String, nullable=True)
    idSegment = db.Column("idsegmento", db.Integer, nullable=False)
    dose = db.Column("dose", db.Float, nullable=True)
    frequency = db.Column("frequenciadia", db.Float, nullable=True)
    doseconv = db.Column("doseconv", db.Float, nullable=True)
    route = db.Column('via', db.String, nullable=True)
    notes = db.Column('complemento', db.String, nullable=True)
    status = db.Column('status', db.String(1), nullable=False)
    near = db.Column("aprox", db.Boolean, nullable=True)
    suspended = db.Column("suspenso", db.Boolean, nullable=True)
    update = db.Column("update_at", db.DateTime, nullable=True)
    user = db.Column("update_by", db.Integer, nullable=True)

    def setSchema(schema):
        PrescriptionDrug.__table__.schema = schema

    def findByPrescription(idPrescription, admissionNumber):
        
        drugChecked = getDrugOption(idPrescription, admissionNumber, 'checked')
        drugIntervention = getDrugOption(idPrescription, admissionNumber, 'intervened')
        drugHistory = getDrugHistory(idPrescription, admissionNumber)

        return db.session\
            .query(PrescriptionDrug, Drug, MeasureUnit, Frequency, Intervention, 
                    func.coalesce(func.coalesce(Outlier.manualScore, Outlier.score), 4).label('score'),
                    drugChecked.label('checked'), drugIntervention.label('intervened'),
                    OutlierObs.notes, drugHistory.label('drugHistory'))\
            .outerjoin(Outlier, Outlier.id == PrescriptionDrug.idOutlier)\
            .outerjoin(Drug, Drug.id == PrescriptionDrug.idDrug)\
            .outerjoin(MeasureUnit, MeasureUnit.id == PrescriptionDrug.idMeasureUnit)\
            .outerjoin(Frequency, Frequency.id == PrescriptionDrug.idFrequency)\
            .outerjoin(Intervention, Intervention.idPrescriptionDrug == PrescriptionDrug.id)\
            .outerjoin(OutlierObs, OutlierObs.id == Outlier.id)\
            .filter(PrescriptionDrug.idPrescription == idPrescription)\
            .order_by(asc(Drug.name))\
            .all()


class Drug(db.Model):
    __tablename__ = 'medicamento'

    id = db.Column("fkmedicamento", db.Integer, primary_key=True)
    idMeasureUnit = db.Column("fkunidademedida", db.String, nullable=False)
    idHospital = db.Column("fkhospital", db.Integer, nullable=False)
    name = db.Column("nome", db.String, nullable=False)
    antimicro = db.Column("antimicro", db.Boolean, nullable=True)
    mav = db.Column("mav", db.Boolean, nullable=True)
    controlled = db.Column("controlados", db.Boolean, nullable=True)
    notdefault = db.Column("naopadronizado", db.Boolean, nullable=True)

    def setSchema(schema):
        Drug.__table__.schema = schema


class MeasureUnit(db.Model):
    __tablename__ = 'unidademedida'

    id = db.Column("fkunidademedida", db.String, primary_key=True)
    idHospital = db.Column("fkhospital", db.Integer, nullable=False)
    description = db.Column("nome", db.String, nullable=False)

    def setSchema(schema):
        MeasureUnit.__table__.schema = schema

class MeasureUnitConvert(db.Model):
    __tablename__ = 'unidadeconverte'

    idMeasureUnit = db.Column("fkunidademedida", db.String, primary_key=True)
    idDrug = db.Column("fkmedicamento", db.Integer, primary_key=True)
    idHospital = db.Column("fkhospital", db.Integer, nullable=False)
    factor = db.Column("fator", db.String, nullable=False)

    def setSchema(schema):
        MeasureUnitConvert.__table__.schema = schema

class InterventionReason(db.Model):
    __tablename__ = 'motivointervencao'

    id = db.Column("idmotivointervencao", db.Integer, primary_key=True)
    description = db.Column("nome", db.String, nullable=False)
    group = db.Column("tipo", db.String, nullable=True)

    def setSchema(schema):
        InterventionReason.__table__.schema = schema

    def findAll():
        return db.session.query(InterventionReason).order_by(InterventionReason.description).all()


class Frequency(db.Model):
    __tablename__ = 'frequencia'

    id = db.Column("fkfrequencia", db.String, primary_key=True)
    description = db.Column("nome", db.String, nullable=False)

    def setSchema(schema):
        Frequency.__table__.schema = schema


class Intervention(db.Model):
    __tablename__ = 'intervencao'

    id = db.Column("idintervencao", db.Integer, primary_key=True)
    idPrescriptionDrug = db.Column("fkpresmed", db.Integer, nullable=False)
    idUser = db.Column("idusuario", db.Integer, nullable=False)
    idInterventionReason = db.Column("idmotivointervencao", db.Integer, nullable=False)
    propagation = db.Column("boolpropaga", db.String, nullable=False)
    notes = db.Column("observacao", db.String, nullable=True)

    def setSchema(schema):
        Intervention.__table__.schema = schema

    def validateIntervention(self):
        if self.idPrescriptionDrug is None:
            raise AssertionError(
                'Medicamento prescrito: preenchimento obrigatório')

        if self.idUser is None:
            raise AssertionError(
                'Usuário responsável: preenchimento obrigatório')

        if self.idInterventionReason is None:
            raise AssertionError(
                'Motivo intervenção: preenchimento obrigatório')

        if self.propagation is None:
            raise AssertionError('Propagação: preenchimento obrigatório')

        if self.propagation != 'S' and self.propagation != 'N':
            raise AssertionError('Propagação: valor deve ser S ou N')

        if self.notes is None:
            raise AssertionError('Observação: preenchimento obrigatório')

        prescriptionDrug = PrescriptionDrug.query.filter(
            PrescriptionDrug.id == self.idPrescriptionDrug).first()
        if (prescriptionDrug is None):
            raise AssertionError(
                'Medicamento prescrito: identificação inexistente')

        interventionReason = InterventionReason.query.filter(
            InterventionReason.id == self.idInterventionReason).first()
        if (interventionReason is None):
            raise AssertionError(
                'Motivo intervenção: identificação inexistente')

    def save(self):
        self.validateIntervention()
        if self.id == None:
            db.session.add(self)

        db.session.commit()


class Segment(db.Model):
    __tablename__ = 'segmento'

    id = db.Column("idsegmento", db.Integer, primary_key=True)
    description = db.Column("nome", db.String, nullable=False)
    minAge = db.Column("idade_min", db.Integer, nullable=False)
    maxAge = db.Column("idade_max", db.Integer, nullable=False)
    minWeight = db.Column("peso_min", db.Float, nullable=False)
    maxWeight = db.Column("peso_max", db.Float, nullable=False)
    status = db.Column("status", db.Integer, nullable=False)

    def setSchema(schema):
        Segment.__table__.schema = schema

    def findAll():
        return db.session\
            .query(Segment)\
            .order_by(asc(Segment.description))\
            .all()


class Department(db.Model):
    __tablename__ = 'setor'

    id = db.Column("fksetor", db.Integer, primary_key=True)
    idHospital = db.Column("fkhospital", db.Integer, nullable=False)
    name = db.Column("nome", db.String, nullable=False)

    def getAll():
        return Department.query.all()

    def setSchema(schema):
        Department.__table__.schema = schema

class SegmentDepartment(db.Model):
    __tablename__ = 'segmentosetor'

    id = db.Column("idsegmento", db.Integer, primary_key=True)
    idHospital = db.Column("fkhospital", db.Integer, primary_key=True)
    idDepartment = db.Column("fksetor", db.Integer, primary_key=True)

    def setSchema(schema):
        SegmentDepartment.__table__.schema = schema

class Exams(db.Model):
    __tablename__ = 'exame'

    idExame = db.Column("fkexame", db.Integer, nullable=False)
    idPatient = db.Column("fkpessoa", db.Integer, primary_key=True)
    date = db.Column("dtexame", db.DateTime, nullable=False)
    typeExam = db.Column("tpexame", db.String, nullable=False)
    value = db.Column("resultado", db.Float, nullable=False)
    unit = db.Column("unidade", db.String, nullable=True)

    def setSchema(schema):
        Exams.__table__.schema = schema

class PrescriptionPic(db.Model):
    __tablename__ = 'prescricaofoto'

    id = db.Column("fkprescricao", db.Integer, primary_key=True)
    picture = db.Column("foto", postgresql.JSON, nullable=False)

    def setSchema(schema):
        PrescriptionPic.__table__.schema = schema