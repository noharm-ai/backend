from sqlalchemy.dialects import postgresql

from .main import db


class AdmissionQueue(db.Model):
    """An admission with a change a consumer has not seen yet: one row per
    consumer (tp_fila, AdmissionQueueEnum) and admission, queued by the
    producers (admission_queue_service.notify) and dequeued by the consumer
    once it ran on it"""

    __tablename__ = "fila_atendimento"

    queue = db.Column("tp_fila", db.Integer, primary_key=True)
    admission_number = db.Column("nratendimento", db.BigInteger, primary_key=True)
    # the last time it was queued: the consumer dequeues only if it did not
    # change while it ran
    queued_at = db.Column("dt_fila", db.DateTime, nullable=False)
    # what queued it since it was last dequeued (AdmissionQueueReasonEnum)
    reasons = db.Column("motivos", postgresql.ARRAY(db.String(50)), nullable=False)
    # the first time it was queued since it was last dequeued
    created_at = db.Column("created_at", db.DateTime, nullable=False)
