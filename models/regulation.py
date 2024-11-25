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
