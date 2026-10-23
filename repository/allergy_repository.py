"""Repository: patient allergies (alergia)"""

from sqlalchemy import func

from models.main import Allergy, Drug, Substance, db


def get_allergy_records(id_patient: int):
    """Every allergy record of the patient, active and inactive, with the drug
    substance of fkmedicamento (drugSctid) next to the record's own sctid.

    fkmedicamento does not always reference a medicamento record, so the drug
    is outer joined: the record can still match a prescribed drug by sctid.
    name is what the screen lists: the substance (the record's sctid when it
    has one, as the alert resolves it) or the drug name as recorded"""

    return (
        db.session.query(
            Allergy.idDrug,
            Allergy.sctid,
            Drug.sctid.label("drugSctid"),
            Allergy.active,
            Allergy.createdAt,
            func.coalesce(Substance.name, Allergy.drugName).label("name"),
        )
        .outerjoin(Drug, Allergy.idDrug == Drug.id)
        .outerjoin(Substance, Substance.id == func.coalesce(Allergy.sctid, Drug.sctid))
        .filter(Allergy.idPatient == id_patient)
        .all()
    )
