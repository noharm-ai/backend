from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, text, and_, desc, asc

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
    idHospital = db.Column("fkhospital", db.Integer, nullable=False)
    idSegment = db.Column("idsegmento", db.Integer, nullable=False)
    date = db.Column("dtprescricao", db.DateTime, nullable=False)
    status = db.Column('status', db.Integer, nullable=False)

    def setSchema(schema):
        Prescription.__table__.schema = schema

    def getPrescription(idPrescription):
        score = getAggScore()

        return db.session\
            .query(
                Prescription, Patient,
                func.trunc((func.extract('epoch', func.current_date(
                )) - func.extract('epoch', Prescription.date)) / 86400).label('daysAgo'), score
            )\
            .join(Patient, and_(Patient.id == Prescription.idPatient))\
            .filter(Prescription.id == idPrescription)\
            .first()

def getAggScore():
    return db.session.query(func.sum(func.coalesce(func.coalesce(Outlier.manualScore, Outlier.score), 4)).label('score'))\
        .select_from(PrescriptionDrug)\
        .outerjoin(Outlier, and_(Outlier.id == PrescriptionDrug.idOutlier))\
        .filter(PrescriptionDrug.idPrescription == Prescription.id)\
        .as_scalar()

def getScoreOne(level):
    return db.session.query(func.count(func.coalesce(func.coalesce(Outlier.manualScore, Outlier.score), 4)).label('scoreOne'))\
        .select_from(PrescriptionDrug)\
        .outerjoin(Outlier, and_(Outlier.id == PrescriptionDrug.idOutlier))\
        .filter(PrescriptionDrug.idPrescription == Prescription.id)\
        .filter(func.coalesce(Outlier.manualScore, Outlier.score) == level)\
        .as_scalar()

def getExams(typeExam):
    return db.session.query(Exams.value)\
        .select_from(Exams)\
        .filter(Exams.idPatient == Prescription.idPatient)\
        .filter(Exams.typeExam == typeExam)\
        .order_by(Exams.date.desc()).limit(1)\
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

    def getPatients(**kwargs):
        score = getAggScore()
        scoreOne = getScoreOne(1)
        scoreTwo = getScoreOne(2)
        scoreThree = getScoreOne(3)
        tgo = getExams('TGO')
        tgp = getExams('TGP')
        cr = getExams('CR')

        q = db.session\
            .query(
                Prescription, Patient,
                func.trunc((func.extract('epoch', func.current_date(
                )) - func.extract('epoch', Prescription.date)) / 86400).label('daysAgo'),
                score.label('score'), scoreOne.label('scoreOne'), scoreTwo.label('scoreTwo'),
                scoreThree.label('scoreThree'), tgo.label('tgo'), tgp.label('tgp'), cr.label('cr')
            )\
            .join(Patient, Patient.id == Prescription.idPatient)

        name = kwargs.get('name', None)
        if (not(name is None)):
            search = "%{}%".format(name)
            q = q.filter(Patient.name.like(search))

        idSegment = kwargs.get('idSegment', None)
        if (not(idSegment is None)):
            q = q.filter(Prescription.idSegment == idSegment)

        q = q.with_labels().subquery()

        prescritionAlias = db.aliased(Prescription, q)
        patientAlias = db.aliased(Patient, q)

        wrapper = db.session\
            .query(prescritionAlias, patientAlias, '"daysAgo"', "score", '"scoreOne"',\
                     '"scoreTwo"', '"scoreThree"', 'tgo', 'tgp', 'cr')\

        order = kwargs.get('order', 'score')
        if (order != 'score'):
            if (order == 'date'):
                order = text('anon_1.prescricao_dthr_prescricao')
            elif (order == 'name'):
                order = text('anon_1.paciente_nome')
            else:
                order = 'score'

        direction = kwargs.get('direction', 'desc')
        if (direction == 'desc'):
            wrapper = wrapper.order_by(desc(order))
        else:
            wrapper = wrapper.order_by(asc(order))

        limit = kwargs.get('limit', 20)

        return wrapper.limit(limit).all()


class Outlier(db.Model):
    __tablename__ = 'outlier'

    id = db.Column("idoutlier", db.Integer, primary_key=True)
    idDrug = db.Column("fkmedicamento", db.Integer, nullable=False)
    idSegment = db.Column("idsegmento", db.Integer, nullable=False)
    countNum = db.Column("contagem", db.Integer, nullable=True)
    dose = db.Column("dose", db.Integer, nullable=True)
    frequency = db.Column("frequenciadia", db.Integer, nullable=True)
    score = db.Column("escore", db.Integer, nullable=True)
    manualScore = db.Column("escoremanual", db.Integer, nullable=True)
    idUser = db.Column("idusuario", db.Integer, nullable=True)

    def setSchema(schema):
        Outlier.__table__.schema = schema


class PrescriptionDrug(db.Model):
    __tablename__ = 'presmed'

    id = db.Column("idpresmed", db.Integer, primary_key=True)
    idOutlier = db.Column("idoutlier", db.Integer, nullable=False)
    idPrescription = db.Column("fkprescricao", db.Integer, nullable=False)
    idDrug = db.Column("fkmedicamento", db.Integer, nullable=False)
    idMeasureUnit = db.Column("fkunidademedida", db.Integer, nullable=False)
    dose = db.Column("dose", db.Integer, nullable=False)
    idFrequency = db.Column("fkfrequencia", db.Integer, nullable=True)
    dose = db.Column("dose", db.Integer, nullable=True)
    route = db.Column('via', db.String, nullable=True)

    def setSchema(schema):
        PrescriptionDrug.__table__.schema = schema

    def findByPrescription(idPrescription):
        #PrescriptionDrugSub = db.aliased(PrescriptionDrug)
        #score = db.session.query(func.sum(func.coalesce(func.coalesce(Outlier.manualScore, Outlier.score), 4)).label('score'))\
        #    .select_from(PrescriptionDrugSub)\
        #    .outerjoin(Outlier.idOutlier == PrescriptionDrugSub.idOutlier)\
        #    .filter(PrescriptionDrug.id == PrescriptionDrugSub.id)\
        #    .as_scalar()

        return db.session\
            .query(PrescriptionDrug, Drug, MeasureUnit, Frequency, Intervention, func.coalesce(func.coalesce(Outlier.manualScore, Outlier.score), 4).label('score'))\
            .join(Outlier, Outlier.id == PrescriptionDrug.idOutlier)\
            .join(Drug, Drug.id == PrescriptionDrug.idDrug)\
            .outerjoin(MeasureUnit, MeasureUnit.id == PrescriptionDrug.idMeasureUnit)\
            .outerjoin(Frequency, Frequency.id == PrescriptionDrug.idFrequency)\
            .outerjoin(Intervention, Intervention.idPrescriptionDrug == PrescriptionDrug.id)\
            .filter(PrescriptionDrug.idPrescription == idPrescription)\
            .all()


class Drug(db.Model):
    __tablename__ = 'medicamento'

    id = db.Column("fkmedicamento", db.Integer, primary_key=True)
    idMeasureUnit = db.Column("fkunidademedida", db.Integer, nullable=False)
    idHospital = db.Column("fkhospital", db.Integer, nullable=False)
    name = db.Column("nome", db.String, nullable=False)

    def setSchema(schema):
        Drug.__table__.schema = schema


class MeasureUnit(db.Model):
    __tablename__ = 'unidademedida'

    id = db.Column("fkunidademedida", db.Integer, primary_key=True)
    idHospital = db.Column("fkhospital", db.Integer, nullable=False)
    description = db.Column("nome", db.String, nullable=False)

    def setSchema(schema):
        MeasureUnit.__table__.schema = schema


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

    id = db.Column("fkfrequencia", db.Integer, primary_key=True)
    description = db.Column("nome", db.String, nullable=False)

    def setSchema(schema):
        Frequency.__table__.schema = schema


class Intervention(db.Model):
    __tablename__ = 'intervencao'

    id = db.Column("idintervencao", db.Integer, primary_key=True)
    idPrescriptionDrug = db.Column("idpresmed", db.Integer, nullable=False)
    idUser = db.Column("idusuario", db.Integer, nullable=False)
    idInterventionReason = db.Column("idmotivointervencao", db.Integer, nullable=False)
    propagation = db.Column("boolpropaga", db.String, nullable=False)
    observation = db.Column("observacao", db.String, nullable=True)

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

        if self.observation is None:
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
    value = db.Column("valor", db.Float, nullable=False)
    unit = db.Column("unidade", db.String, nullable=True)

    def setSchema(schema):
        Exams.__table__.schema = schema