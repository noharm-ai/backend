from sqlalchemy.orm import undefer

from models.main import db, Substance, SubstanceClass, User


def get_by_id(substance_id: int):
    return (
        db.session.query(Substance, SubstanceClass, User)
        .outerjoin(SubstanceClass, SubstanceClass.id == Substance.idclass)
        .outerjoin(User, Substance.updatedBy == User.id)
        .options(undefer(Substance.handling), undefer(Substance.admin_text))
        .filter(Substance.id == substance_id)
        .first()
    )
