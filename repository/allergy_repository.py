"""Repository: patient allergies (alergia)"""

from sqlalchemy import desc, func, nullslast
from sqlalchemy.orm import aliased

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


def list_allergy_records(id_patient: int):
    """Every allergy record of the patient as it is stored, for maintainers to
    inspect: the drug of fkmedicamento with its substance when the drug
    exists, and the record's own name and sctid with their substance.

    Columns, not Allergy entities: fkmedicamento can be null, and the model
    maps it as part of the primary key"""

    drug_substance = aliased(Substance)
    record_substance = aliased(Substance)

    return (
        db.session.query(
            Allergy.idDrug,
            Allergy.drugName,
            Allergy.sctid,
            Allergy.active,
            Allergy.createdAt,
            Drug.id.label("drugId"),
            Drug.name.label("drugCatalogName"),
            Drug.sctid.label("drugSctid"),
            drug_substance.name.label("drugSubstanceName"),
            record_substance.name.label("substanceName"),
        )
        .outerjoin(Drug, Allergy.idDrug == Drug.id)
        .outerjoin(drug_substance, drug_substance.id == Drug.sctid)
        .outerjoin(record_substance, record_substance.id == Allergy.sctid)
        .filter(Allergy.idPatient == id_patient)
        .order_by(desc(Allergy.active), nullslast(desc(Allergy.createdAt)))
        .all()
    )
