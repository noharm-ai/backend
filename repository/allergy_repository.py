"""Repository: patient allergies (alergia)"""

from datetime import datetime

from sqlalchemy import desc, func, nullslast, update
from sqlalchemy.orm import aliased

from models.main import Allergy, Drug, Substance, db


def get_allergy_records(id_patient: int):
    """Every allergy record of the patient, active and inactive, with the drug
    substance of fkmedicamento (drugSctid) next to the record's own sctid.

    fkmedicamento does not always reference a medicamento record, so the drug
    is outer joined: the record can still match a prescribed drug by sctid.
    name is what the screen lists: the substance (the record's sctid when it
    has one, as the alert resolves it) or the drug name as recorded. drugId
    (the medicamento found, if any), drugName and substance tell which"""

    return (
        db.session.query(
            Allergy.idDrug,
            Allergy.sctid,
            Drug.sctid.label("drugSctid"),
            Allergy.active,
            Allergy.createdAt,
            func.coalesce(Substance.name, Allergy.drugName).label("name"),
            Drug.id.label("drugId"),
            Allergy.drugName,
            Substance.name.label("substance"),
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


def update_sctid(
    id_drug: int | None, drug_name: str | None, sctid: int | None, id_user: int
):
    """Set (or remove, with no sctid) the substance of every allergy record (of
    every patient) with the given fkmedicamento and nome_medicamento, returning
    the row count"""

    return db.session.execute(
        update(Allergy)
        .where(Allergy.idDrug.is_not_distinct_from(id_drug))
        .where(Allergy.drugName.is_not_distinct_from(drug_name))
        .values(sctid=sctid, updatedAt=datetime.now(), updatedBy=id_user)
        .execution_options(synchronize_session=False)
    ).rowcount
