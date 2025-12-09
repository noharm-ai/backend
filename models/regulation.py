from sqlalchemy.dialects import postgresql

from .main import db


class RegSolicitation(db.Model):
    __tablename__ = "reg_solicitacao"

    id = db.Column("fkreg_solicitacao", db.BigInteger, primary_key=True)
    admission_number = db.Column("nratendimento", db.BigInteger, nullable=False)
    id_patient = db.Column("fkpessoa", db.BigInteger, nullable=False)
    date = db.Column("dtsolicitacao", db.DateTime, nullable=False)
    id_reg_solicitation_type = db.Column(
        "fkreg_tipo_solicitacao", db.BigInteger, nullable=False
    )
    id_department = db.Column("fksetor", db.BigInteger, nullable=False)

    risk = db.Column("risco", db.Integer, nullable=True)
    cid = db.Column("cid", db.String, nullable=True)
    attendant = db.Column("atendente", db.String, nullable=True)
    attendant_record = db.Column("atendente_registro", db.String, nullable=True)
    justification = db.Column("justificativa", db.String, nullable=True)

    stage = db.Column("etapa", db.Integer, nullable=False)
    schedule_date = db.Column("dtagendamento", db.DateTime, nullable=True)
    transportation_date = db.Column("dttransporte", db.DateTime, nullable=True)

    created_at = db.Column("created_at", db.DateTime, nullable=False)
    created_by = db.Column("created_by", db.BigInteger, nullable=True)
    updated_at = db.Column("updated_at", db.DateTime, nullable=False)
    updated_by = db.Column("updated_by", db.BigInteger, nullable=True)


class RegSolicitationAttribute(db.Model):
    """Solicitation attributes"""

    __tablename__ = "reg_solicitacao_atributo"

    id = db.Column("idreg_solicitacao_atributo", db.BigInteger, primary_key=True)
    id_reg_solicitation = db.Column("fkreg_solicitacao", db.BigInteger, nullable=False)
    tp_attribute = db.Column("tp_solicitacao_atributo", db.Integer, nullable=False)
    tp_status = db.Column("tp_status", db.Integer, nullable=False)
    value = db.Column("valor", postgresql.JSONB, nullable=False)

    created_at = db.Column("created_at", db.DateTime, nullable=False)
    created_by = db.Column("created_by", db.BigInteger, nullable=True)
    updated_at = db.Column("updated_at", db.DateTime, nullable=False)
    updated_by = db.Column("updated_by", db.BigInteger, nullable=True)


class RegSolicitationType(db.Model):
    __tablename__ = "reg_tipo_solicitacao"

    id = db.Column("fkreg_tipo_solicitacao", db.BigInteger, primary_key=True)
    name = db.Column("nome", db.String, nullable=False)
    status = db.Column("status", db.Integer, nullable=False)
    tp_type = db.Column("tp_tipo", db.Integer, nullable=False)

    created_at = db.Column("created_at", db.DateTime, nullable=False)
    created_by = db.Column("created_by", db.BigInteger, nullable=True)
    updated_at = db.Column("updated_at", db.DateTime, nullable=False)
    updated_by = db.Column("updated_by", db.BigInteger, nullable=True)


class RegMovement(db.Model):
    __tablename__ = "reg_movimentacao"

    id = db.Column("idreg_movimentacao", db.BigInteger, primary_key=True)
    id_reg_solicitation = db.Column("fkreg_solicitacao", db.BigInteger, nullable=False)
    stage_origin = db.Column("etapa_origem", db.Integer, nullable=False)
    stage_destination = db.Column("etapa_destino", db.Integer, nullable=False)
    action = db.Column("acao", db.Integer, nullable=False)
    data = db.Column("dados", postgresql.JSON, nullable=False)
    template = db.Column("template", postgresql.JSON, nullable=False)

    created_at = db.Column("created_at", db.DateTime, nullable=False)
    created_by = db.Column("created_by", db.BigInteger, nullable=True)


class RegIndicatorsPanelReport(db.Model):
    __tablename__ = "rel_painel_juntos"

    id = db.Column("co_unico_ficha", db.BigInteger, primary_key=True)

    id_citizen = db.Column("co_seq_cidadao", db.String, nullable=True)
    admission_number = db.Column("nratendimento", db.BigInteger, nullable=True)
    name = db.Column("nome", db.String, nullable=True)
    birthdate = db.Column("dtnascimento", db.Date, nullable=True)
    age = db.Column("idade", db.Integer, nullable=True)
    address = db.Column("endereco", db.String, nullable=True)
    gender = db.Column("sexo", db.String, nullable=True)
    gestational_age = db.Column("idadegestacional", db.String, nullable=True)
    cpf = db.Column("cpf", db.String, nullable=True)
    cns = db.Column("cns", db.String, nullable=True)
    health_unit = db.Column("unidadedesaude", db.String, nullable=True)
    health_agent = db.Column("agentesaude", db.String, nullable=True)
    responsible_team = db.Column("equiperesponsavel", db.String, nullable=True)
    ciap = db.Column("desc_ciap", db.String, nullable=True)
    icd = db.Column("desc_cid", db.String, nullable=True)
    mammogram_appointment_date = db.Column("dtatendimento_mamo", db.Date, nullable=True)
    hpv_appointment_date = db.Column("dtatendimento_hpv", db.Date, nullable=True)
    hpv_vaccine_date = db.Column("dt_ultima_vacina_hpv", db.Date, nullable=True)
    gestational_appointment_date = db.Column("dtconsulta_gest", db.Date, nullable=True)
    sexattention_appointment_date = db.Column(
        "dtatendimento_sex", db.Date, nullable=True
    )
    has_mammogram = db.Column("fez_mamografia", db.Boolean, nullable=True)
    has_hpv = db.Column("fez_hpv", db.Boolean, nullable=True)
    has_vaccine = db.Column("fez_vacina", db.Boolean, nullable=True)
    has_sexattention_appointment = db.Column(
        "fez_consulta_sex", db.Boolean, nullable=True
    )
    has_gestational_appointment = db.Column(
        "fez_consulta_gest", db.Boolean, nullable=True
    )
