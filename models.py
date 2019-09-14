from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, text, and_, desc, asc

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'usuario'

    id = db.Column("idusuario", db.Integer, primary_key=True)
    idHospital = db.Column('idhospital', db.Integer, nullable=False)
    name = db.Column('nome', db.String(250), nullable=False)
    cpf = db.Column('cpf', db.String(11), nullable=False)
    email = db.Column("email", db.String(254), unique=True, nullable=False)
    password = db.Column('senha', db.String(128), nullable=False)

    def find(id):
      return User.query.filter(User.id == id).first()

    def authenticate(email, password):
      return User.query.filter_by(email = email, password = password).first()

class Prescription(db.Model):
    __tablename__ = 'prescricao'

    id = db.Column("idprescricao", db.Integer, primary_key=True)
    idPatient = db.Column("idpaciente", db.Integer, nullable=False)
    idHospital = db.Column("idhospital", db.Integer, nullable=True)
    date = db.Column("dthr_prescricao", db.DateTime, nullable=False)
    status = db.Column('status', db.Integer, nullable=False)

    def getPrescription(idPrescription):
        #TODO: rever calculo do score. considerar hospital, segmento e versao. CRIAR FUNCAO
        score = db.session.query(func.sum(func.ifnull(func.ifnull(Outlier.manualScore, Outlier.score), 4)).label('score'))\
          .select_from(PrescriptionDrug)\
          .outerjoin(\
            Outlier,\
            and_(Outlier.idDrug == PrescriptionDrug.idDrug, Outlier.frequency == PrescriptionDrug.frequency, Outlier.dose == PrescriptionDrug.dose)\
          )\
          .filter(PrescriptionDrug.idPrescription == Prescription.id)\
          .as_scalar()

        return db.session\
          .query(Prescription, Patient, Risk, func.datediff(func.current_date(), Prescription.date).label('daysAgo'), score)\
          .join(Patient, and_(Patient.id == Prescription.idPatient))\
          .join(Risk, Patient.idRisk == Risk.id)\
          .filter(Prescription.id == idPrescription)\
          .first()

class Patient(db.Model):
    __tablename__ = 'paciente'

    id = db.Column("idpaciente", db.Integer, primary_key=True)
    idHospital = db.Column("idhospital", db.Integer, nullable=False)
    idRisk = db.Column("idclassrisco", db.Integer, nullable=False)
    name = db.Column('nome', db.String(250), nullable=False)

    def getPatients(idHospital, **kwargs):
        #TODO: rever calculo do score. considerar hospital, segmento e versao. CRIAR FUNCAO
        score = db.session.query(func.sum(func.ifnull(func.ifnull(Outlier.manualScore, Outlier.score), 4)).label('score'))\
          .select_from(PrescriptionDrug)\
          .outerjoin(\
            Outlier,\
            and_(Outlier.idDrug == PrescriptionDrug.idDrug, Outlier.frequency == PrescriptionDrug.frequency, Outlier.dose == PrescriptionDrug.dose)\
          )\
          .filter(PrescriptionDrug.idPrescription == Prescription.id)\
          .as_scalar()
        
        #TODO: considerar status da prescricao
        q = db.session\
          .query(Prescription, Patient, func.datediff(func.current_date(), Prescription.date).label('daysAgo'), Risk, score.label('score'))\
          .join(Patient, Patient.id == Prescription.idPatient)\
          .join(Risk, Patient.idRisk == Risk.id)\
          .filter(Prescription.idHospital == idHospital)\

        name = kwargs.get('name', None)
        
        if (not(name is None)):
          search = "%{}%".format(name)
          q = q.filter(Patient.name.like(search))

        q = q.with_labels().subquery()

        prescritionAlias = db.aliased(Prescription, q)
        patientAlias = db.aliased(Patient, q)
        riskAlias = db.aliased(Risk, q)

        wrapper = db.session\
          .query(prescritionAlias, patientAlias, riskAlias, 'daysAgo', 'score')\

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

    id = db.Column("idOutlier", db.Integer, primary_key=True)
    idHospital = db.Column("idhospital", db.Integer, nullable=False)
    idDrug = db.Column("idmedicamento", db.Integer, nullable=False)
    idMeasureUnit = db.Column("idunidmedida", db.Integer, nullable=False)
    countNum = db.Column("contagem", db.Integer, nullable=True)
    version = db.Column("versao", db.Integer, nullable=True)
    dose = db.Column("dose", db.Integer, nullable=True)
    frequency = db.Column("frequencia", db.Integer, nullable=True)
    score = db.Column("escore", db.Integer, nullable=True)
    manualScore = db.Column("escoremanual", db.Integer, nullable=True)
    status = db.Column("status", db.Integer, nullable=False)

class Risk(db.Model):
    __tablename__ = 'classificacaorisco'

    id = db.Column("idclassrisco", db.Integer, primary_key=True)
    description = db.Column('descricao', db.String, nullable=False)

class PrescriptionDrug(db.Model):
    __tablename__ = 'prescricaomedicamento'

    id = db.Column("idpresmed", db.Integer, primary_key=True)
    idPrescription = db.Column("idprescricao", db.Integer, nullable=False)
    idDrug = db.Column("idmedicamento", db.Integer, nullable=False)
    idMeasureUnit = db.Column("idunidmedida", db.Integer, nullable=False)
    dose = db.Column("dose", db.Integer, nullable=False)
    frequency = db.Column("frequencia", db.Integer, nullable=True)
    dose = db.Column("dose", db.Integer, nullable=True)
    idAdministration = db.Column('via', db.Integer, nullable=True)

    def findByPrescription(idPrescription):
        PrescriptionDrugSub = db.aliased(PrescriptionDrug)
        #TODO: rever calculo do score. considerar hospital, segmento e versao. CRIAR FUNCAO
        score = db.session.query(func.sum(func.ifnull(func.ifnull(Outlier.manualScore, Outlier.score), 4)).label('score'))\
          .select_from(PrescriptionDrugSub)\
          .outerjoin(\
            Outlier,\
            and_(\
              Outlier.idDrug == PrescriptionDrugSub.idDrug, Outlier.frequency == PrescriptionDrugSub.frequency,\
              Outlier.dose == PrescriptionDrugSub.dose
            )\
          )\
          .filter(PrescriptionDrug.id == PrescriptionDrugSub.id)\
          .as_scalar()

        #TODO: order by
        return db.session\
          .query(PrescriptionDrug, Drug, MeasureUnit, Administration, score, Frequency)\
          .join(Drug, Drug.id == PrescriptionDrug.idDrug)\
          .join(MeasureUnit, MeasureUnit.id == PrescriptionDrug.idMeasureUnit)\
          .join(Administration, Administration.id == PrescriptionDrug.idAdministration)\
          .join(Frequency, Frequency.id == PrescriptionDrug.frequency)\
          .filter(PrescriptionDrug.idPrescription == idPrescription)\
          .all()

class Drug(db.Model):
    __tablename__ = 'medicamento'

    id = db.Column("idmedicamento", db.Integer, primary_key=True)
    idMeasureUnit = db.Column("idunidmedida", db.Integer, nullable=False)
    idHospital = db.Column("idhospital", db.Integer, nullable=False)
    name = db.Column("nome", db.String, nullable=False)

class MeasureUnit(db.Model):
    __tablename__ = 'unidadesmedida'

    id = db.Column("idunidmedida", db.Integer, primary_key=True)
    idHospital = db.Column("idhospital", db.Integer, nullable=False)
    description = db.Column("descricao", db.String, nullable=False)

class Administration(db.Model):
    __tablename__ = 'viaadministracao'

    id = db.Column("idviaadmin", db.Integer, primary_key=True)
    idHospital = db.Column("idhospital", db.Integer, nullable=False)
    description = db.Column("descricao", db.String, nullable=False)

class InterventionReason(db.Model):
    __tablename__ = 'motivointervencao'

    id = db.Column("idmotivointerv", db.Integer, primary_key=True)
    description = db.Column("descricao", db.String, nullable=False)

class Frequency(db.Model):
    __tablename__ = 'tipofrequencia'

    id = db.Column("idtipofreq", db.Integer, primary_key=True)
    description = db.Column("descricao", db.String, nullable=False)

class Intervention(db.Model):
    __tablename__ = 'intervencao'

    id = db.Column("idintervencao", db.Integer, primary_key=True)
    idPrescriptionDrug = db.Column("idpresmed", db.Integer, nullable=False)
    idPrescription = db.Column("idprescricao", db.Integer, nullable=False)
    idUser = db.Column("idusuario", db.Integer, nullable=False)
    idDrug = db.Column("idmedicamento", db.Integer, nullable=False)
    idInterventionReason = db.Column("idmotivointerv", db.Integer, nullable=False)
    propagation = db.Column("propaga", db.String, nullable=False)
    observation = db.Column("observacoes", db.String, nullable=True)

    def validateIntervention(self):
        if self.idPrescriptionDrug is None:
          raise AssertionError('Medicamento prescrito: preenchimento obrigatório')

        if self.idUser is None:
          raise AssertionError('Usuário responsável: preenchimento obrigatório')

        if self.idInterventionReason is None:
          raise AssertionError('Motivo intervenção: preenchimento obrigatório')

        if self.propagation is None:
          raise AssertionError('Propagação: preenchimento obrigatório')

        if self.propagation != 'S' and self.propagation != 'N':
          raise AssertionError('Propagação: valor deve ser S ou N')

        if self.observation is None:
          raise AssertionError('Observação: preenchimento obrigatório')

        prescriptionDrug = PrescriptionDrug.query.filter(PrescriptionDrug.id == self.idPrescriptionDrug).first()
        if (prescriptionDrug is None):
            raise AssertionError('Medicamento prescrito: identificação inexistente')

        interventionReason = InterventionReason.query.filter(InterventionReason.id == self.idInterventionReason).first()
        if (interventionReason is None):
            raise AssertionError('Motivo intervenção: identificação inexistente')

    def save(self):
        self.validateIntervention()

        db.session.add(self)
        db.session.commit()