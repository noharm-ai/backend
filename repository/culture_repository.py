"""Repository: culture related operations"""

from datetime import datetime

from boto3.dynamodb.conditions import Key
from sqlalchemy import desc, func, select
from sqlalchemy.dialects.postgresql import distinct_on

from config import Config
from models.appendix import Culture, CultureHeader
from models.enums import NoHarmENV
from models.main import db
from utils import aws


def get_culture_summary_from_dynamodb(schema: str, id_patient: int):
    """Get the culture summary (antibiogram + prediction) by patient from DynamoDB"""

    if Config.ENV == NoHarmENV.TEST.value:
        return []

    dynamodb = aws.get_resource("dynamodb", region_name="sa-east-1")
    table = dynamodb.Table("noharm_cultura_resumo")

    PARTITION_KEY_VALUE = f"{schema}:{id_patient}"

    response = table.query(
        KeyConditionExpression=Key("schema_fkpessoa").eq(PARTITION_KEY_VALUE),
    )

    return response.get("Items", [])


# what the infection control page shows of a culture header
_HEADER_COLUMNS = (
    CultureHeader.id,
    CultureHeader.idExamItem,
    CultureHeader.examName,
    CultureHeader.examMaterialName,
    CultureHeader.collectionDate,
    CultureHeader.releaseDate,
    CultureHeader.gram,
    CultureHeader.previousResult,
)


def get_latest_culture_headers(id_patient: int, released_since: datetime) -> list:
    """The latest culture of each exam and material of the patient, among the
    ones released since the given date.

    The latest is the newest collection, whatever it says: a collection still
    waiting for the lab also gets a release date (about the collection time),
    so it counts as fresh and takes the place of the older result.
    """

    query = (
        select(*_HEADER_COLUMNS)
        .where(CultureHeader.idPatient == id_patient)
        .where(CultureHeader.releaseDate >= released_since)
        .ext(distinct_on(CultureHeader.examName, CultureHeader.examMaterialName))
        .order_by(
            CultureHeader.examName,
            CultureHeader.examMaterialName,
            desc(CultureHeader.collectionDate).nulls_last(),
            desc(CultureHeader.releaseDate),
            desc(CultureHeader.id),
        )
    )

    return db.session.execute(query).all()


def get_culture_header(id_culture: int, id_patient: int):
    """A culture header of the patient, or None when it is not the patient's"""

    query = (
        select(*_HEADER_COLUMNS)
        .where(CultureHeader.id == id_culture)
        .where(CultureHeader.idPatient == id_patient)
    )

    return db.session.execute(query).first()


def get_culture_headers_of_exam(
    id_patient: int, exam_name: str | None, material: str | None, limit: int
) -> list:
    """Every culture of the patient with this exam and material, newest
    collection first. A missing name matches a missing name, as the latest
    culture of each exam and material groups them (DISTINCT ON)."""

    query = (
        select(*_HEADER_COLUMNS)
        .where(CultureHeader.idPatient == id_patient)
        .where(CultureHeader.examName.is_not_distinct_from(exam_name))
        .where(CultureHeader.examMaterialName.is_not_distinct_from(material))
        .order_by(
            desc(CultureHeader.collectionDate).nulls_last(),
            desc(CultureHeader.releaseDate),
            desc(CultureHeader.id),
        )
        .limit(limit)
    )

    return db.session.execute(query).all()


def get_cultures_collected(
    id_patient: int, collected_since: datetime, collected_until: datetime
) -> list:
    """The patient's cultures collected between two dates, oldest first"""

    query = (
        select(CultureHeader.id, CultureHeader.idExamItem, CultureHeader.collectionDate)
        .where(CultureHeader.idPatient == id_patient)
        .where(CultureHeader.collectionDate >= collected_since)
        .where(CultureHeader.collectionDate <= collected_until)
        .order_by(CultureHeader.collectionDate, CultureHeader.id)
    )

    return db.session.execute(query).all()


def get_microorganisms(id_exam_items: list[int]) -> dict[int, list[str]]:
    """The microorganisms the antibiogram rows (cultura) name for each exam
    item. A row with no microorganism is a prediction or a pending one."""

    if not id_exam_items:
        return {}

    query = (
        select(Culture.idExamItem, Culture.microorganism)
        .where(Culture.idExamItem.in_(id_exam_items))
        .where(func.trim(Culture.microorganism) != "")
        .distinct()
    )

    microorganisms = {}
    for row in db.session.execute(query).all():
        microorganisms.setdefault(row.idExamItem, []).append(row.microorganism.strip())

    return {
        id_exam_item: sorted(set(names))
        for id_exam_item, names in microorganisms.items()
    }


def get_antibiograms(id_exam_items: list[int]) -> dict[int, list]:
    """The released antibiogram rows (cultura) of each exam item. A row with
    no result is a prediction or a pending one, and is left out: a prediction
    must never be read as the lab's result."""

    if not id_exam_items:
        return {}

    query = (
        select(
            Culture.idExamItem,
            Culture.microorganism,
            Culture.drug,
            Culture.result,
            Culture.microorganismAmount,
        )
        .where(Culture.idExamItem.in_(id_exam_items))
        .where(func.trim(Culture.result) != "")
        .where(func.trim(Culture.drug) != "")
        .order_by(Culture.microorganism, Culture.drug, Culture.id)
    )

    antibiograms = {}
    for row in db.session.execute(query).all():
        antibiograms.setdefault(row.idExamItem, []).append(row)

    return antibiograms
