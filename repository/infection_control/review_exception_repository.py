"""Repository: the antimicrobials the infection control review exceptions can
list (the list itself is a setting, see settings_repository)"""

from sqlalchemy import BigInteger, column, func, or_
from sqlalchemy.dialects.postgresql import JSONB

from models.enums import InfectionControlStatusEnum
from models.infection_control import InfectionControlAdmission
from models.main import Drug, DrugAttributes, Substance, db


def _is_antimicrobial():
    """Whether the drug of the outer query is flagged antimicrobial
    (antimicro) in some segment"""
    return (
        db.session.query(DrugAttributes.idDrug)
        .filter(DrugAttributes.idDrug == Drug.id)
        .filter(DrugAttributes.antimicro == True)
        .exists()
    )


def search_substances(
    term: str | None = None, id_substances: set[int] | None = None, limit: int = 50
) -> list[tuple[int, str]]:
    """Substances of the schema's antimicrobial drugs, by name"""
    has_antimicrobial = (
        db.session.query(Drug.id)
        .filter(Drug.sctid == Substance.id)
        .filter(_is_antimicrobial())
        .exists()
    )
    query = db.session.query(Substance.id, Substance.name).filter(has_antimicrobial)
    if term:
        query = query.filter(Substance.name.ilike(f"%{term}%"))
    if id_substances is not None:
        query = query.filter(Substance.id.in_(id_substances))

    return query.order_by(Substance.name, Substance.id).limit(limit).all()


def search_drugs_without_substance(
    term: str | None = None, limit: int = 50
) -> list[tuple[int, str]]:
    """Antimicrobial drugs without a substance (listed by drug), by name"""
    query = (
        db.session.query(Drug.id, Drug.name)
        .filter(Drug.sctid == None)
        .filter(_is_antimicrobial())
    )
    if term:
        query = query.filter(Drug.name.ilike(f"%{term}%"))

    return query.order_by(Drug.name, Drug.id).limit(limit).all()


def get_substance_names(id_substances: set[int]) -> dict[int, str]:
    """Names of substances, by id"""
    if not id_substances:
        return {}

    return dict(
        db.session.query(Substance.id, Substance.name)
        .filter(Substance.id.in_(id_substances))
        .all()
    )


def get_followed_running(id_drugs: set[int], id_substances: set[int]) -> list[int]:
    """The followed admissions (pending or revised) running a course of any of
    the drugs or substances, as the rule last kept them (indicadores)"""
    if not id_drugs and not id_substances:
        return []

    course = (
        func.jsonb_array_elements(InfectionControlAdmission.features["courses"])
        .table_valued(column("value", JSONB))
        .alias("course")
    )
    runs_one = (
        db.session.query(course)
        .filter(
            or_(
                course.c.value["idDrug"].astext.cast(BigInteger).in_(id_drugs),
                course.c.value["idSubstance"]
                .astext.cast(BigInteger)
                .in_(id_substances),
            )
        )
        .exists()
    )

    return [
        row.admission_number
        for row in db.session.query(InfectionControlAdmission.admission_number)
        .filter(
            InfectionControlAdmission.status.in_(
                [
                    InfectionControlStatusEnum.PENDING.value,
                    InfectionControlStatusEnum.REVISED.value,
                ]
            )
        )
        .filter(runs_one)
        .order_by(InfectionControlAdmission.admission_number)
        .all()
    ]
