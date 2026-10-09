from sqlalchemy.dialects import postgresql

from .main import db


class InfectionControlAdmission(db.Model):
    """Infection control status of an admission"""

    __tablename__ = "ci_atendimento"

    admission_number = db.Column("nratendimento", db.BigInteger, primary_key=True)
    status = db.Column("tp_status", db.Integer, nullable=False)
    status_date = db.Column("dt_status", db.DateTime, nullable=False)
    next_review_date = db.Column("dt_proxima_revisao", db.DateTime, nullable=True)
    id_last_review = db.Column("fkci_revisao_ultima", db.BigInteger, nullable=True)
    origin = db.Column("tp_origem", db.Integer, nullable=False)
    recalculated_at = db.Column("dt_recalculo", db.DateTime, nullable=False)

    updated_at = db.Column("updated_at", db.DateTime, nullable=True)
    updated_by = db.Column("updated_by", db.Integer, nullable=True)
    created_at = db.Column("created_at", db.DateTime, nullable=False)
    created_by = db.Column("created_by", db.Integer, nullable=False)


class InfectionControlReview(db.Model):
    """One review of the patient by the infectologist"""

    __tablename__ = "ci_revisao"

    id = db.Column("idci_revisao", db.BigInteger, primary_key=True, autoincrement=True)
    admission_number = db.Column("nratendimento", db.BigInteger, nullable=False)
    notes = db.Column("observacao", db.String, nullable=True)
    next_review_date = db.Column("dt_proxima_revisao", db.DateTime, nullable=True)

    created_at = db.Column("created_at", db.DateTime, nullable=False)
    created_by = db.Column("created_by", db.Integer, nullable=False)


class AntimicrobialEvaluation(db.Model):
    """Conformity of one antimicrobial course, recorded in a review"""

    __tablename__ = "ci_avaliacao_atm"

    id = db.Column(
        "idci_avaliacao_atm", db.BigInteger, primary_key=True, autoincrement=True
    )
    id_review = db.Column("fkci_revisao", db.BigInteger, nullable=False)
    admission_number = db.Column("nratendimento", db.BigInteger, nullable=False)
    id_drug = db.Column("fkmedicamento", db.BigInteger, nullable=False)
    id_prescription = db.Column("fkprescricao", db.BigInteger, nullable=False)
    id_prescription_drug = db.Column("fkpresmed", db.BigInteger, nullable=False)
    course_start = db.Column("dt_inicio_curso", db.DateTime, nullable=False)
    conforming = db.Column("conforme", db.Boolean, nullable=False)
    notes = db.Column("observacao", db.String, nullable=True)
    posology = db.Column("posologia", postgresql.JSONB, nullable=False)
    # when the verdict starts to apply: the review, or earlier when the
    # infectologist backdates it (up to the course start)
    valid_from = db.Column("dt_inicio_validade", db.DateTime, nullable=False)
    valid_until = db.Column("dt_validade", db.DateTime, nullable=False)
    # optional reasons this evaluation watches for (tp_pendencia values)
    triggers = db.Column("gatilhos", postgresql.JSONB, nullable=False)
    status = db.Column("tp_status", db.Integer, nullable=False)
    closed_at = db.Column("dt_encerramento", db.DateTime, nullable=True)
    closing_type = db.Column("tp_encerramento", db.Integer, nullable=True)
    id_superseded_by = db.Column(
        "fkci_avaliacao_atm_substituta", db.BigInteger, nullable=True
    )

    updated_at = db.Column("updated_at", db.DateTime, nullable=True)
    updated_by = db.Column("updated_by", db.Integer, nullable=True)
    created_at = db.Column("created_at", db.DateTime, nullable=False)
    created_by = db.Column("created_by", db.Integer, nullable=False)


class InfectionControlPending(db.Model):
    """One reason that keeps an admission pending, open until resolved"""

    __tablename__ = "ci_pendencia"

    id = db.Column(
        "idci_pendencia", db.BigInteger, primary_key=True, autoincrement=True
    )
    admission_number = db.Column("nratendimento", db.BigInteger, nullable=False)
    pending_type = db.Column("tp_pendencia", db.Integer, nullable=False)
    origin = db.Column("tp_origem", db.Integer, nullable=False)
    id_prescription = db.Column("fkprescricao", db.BigInteger, nullable=True)
    id_drug = db.Column("fkmedicamento", db.BigInteger, nullable=True)
    id_evaluation = db.Column("fkci_avaliacao_atm", db.BigInteger, nullable=True)
    id_alert = db.Column("fkci_alerta", db.BigInteger, nullable=True)
    details = db.Column("detalhes", postgresql.JSONB, nullable=True)

    resolved_at = db.Column("dt_resolucao", db.DateTime, nullable=True)
    resolution_type = db.Column("tp_resolucao", db.Integer, nullable=True)
    id_review = db.Column("fkci_revisao", db.BigInteger, nullable=True)
    resolved_by = db.Column("resolvido_por", db.Integer, nullable=True)

    created_at = db.Column("created_at", db.DateTime, nullable=False)
    created_by = db.Column("created_by", db.Integer, nullable=False)
