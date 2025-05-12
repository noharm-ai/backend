from sqlalchemy.orm import deferred
from sqlalchemy.dialects import postgresql

from .main import db


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
    origin_created_at = db.Column("dtcriacao_origem", db.DateTime, nullable=True)

    def getFuturePrescription(idPrescription, admissionNumber):
        return (
            db.session.query(Prescription)
            .filter(Prescription.admissionNumber == admissionNumber)
            .filter(Prescription.id > idPrescription)
            .first()
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
    st_conciliation = db.Column("st_concilia", db.Integer, nullable=True)
    tags = db.Column("marcadores", postgresql.ARRAY(db.String(100)), nullable=True)
    responsiblePhysician = db.Column("medico_responsavel", db.String, nullable=True)
    id_icd = db.Column("idcid", db.String, nullable=True)
    dischargeDateForecast = db.Column("dt_alta_prevista", db.DateTime, nullable=True)

    def findByAdmission(admissionNumber):
        return (
            db.session.query(Patient)
            .filter(Patient.admissionNumber == admissionNumber)
            .first()
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
    schedule = db.Column("aprazamento", postgresql.ARRAY(db.DateTime), nullable=True)


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

    ram = db.Column("ram", postgresql.JSONB, nullable=True)
