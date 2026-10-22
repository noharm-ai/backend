"""Repository: patient allergies (alergia)"""

from models.main import Allergy, Drug, db


def get_allergy_records(id_patient: int):
    """Every allergy record of the patient, active and inactive, with the drug
    substance of fkmedicamento (drugSctid) next to the record's own sctid.

    fkmedicamento does not always reference a medicamento record, so the drug
    is outer joined: the record can still match a prescribed drug by sctid"""

    return (
        db.session.query(
            Allergy.idDrug,
            Allergy.sctid,
            Drug.sctid.label("drugSctid"),
            Allergy.active,
        )
        .outerjoin(Drug, Allergy.idDrug == Drug.id)
        .filter(Allergy.idPatient == id_patient)
        .all()
    )
