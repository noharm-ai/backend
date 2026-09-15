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


def get_antimicrobial_levels(sctids: list) -> dict:
    """The AWaRe level of each substance, keyed by sctid.

    Read when the culture card compares the antibiogram to the prescription
    (services/culture_service): a substance that is missing from the result
    has no classification.
    """

    ids = list({int(sctid) for sctid in sctids or [] if sctid is not None})

    if not ids:
        return {}

    rows = (
        db.session.query(Substance.id, Substance.name, Substance.atb_level)
        .filter(Substance.id.in_(ids))
        .all()
    )

    return {int(row.id): {"name": row.name, "atbLevel": row.atb_level} for row in rows}
