"""Repository: prescription drug related operations"""

from sqlalchemy import select

from models.main import User, db
from models.prescription import checkedindex_table


def get_drug_check_history(admission_number: int, id_drug: int):
    """Get check history for a drug in a given admission from checkedindex table"""
    ci = checkedindex_table.c

    stmt = (
        select(
            ci.dose,
            ci.doseconv,
            ci.frequenciadia,
            ci.via,
            ci.horario,
            ci.sletapas,
            ci.slhorafase,
            ci.sltempoaplicacao,
            ci.sldosagem,
            ci.complemento,
            ci.fkprescricao,
            ci.dtprescricao,
            ci.created_at,
            User.name.label("user_name"),
        )
        .outerjoin(User.__table__, ci.created_by == User.id)
        .where(ci.nratendimento == admission_number)
        .where(ci.fkmedicamento == id_drug)
        .order_by(ci.created_at.desc())
        .limit(100)
    )

    return db.session.execute(stmt).fetchall()
