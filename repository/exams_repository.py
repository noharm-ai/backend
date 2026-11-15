"""Repository: exams related operations"""

from datetime import date, datetime, timedelta

from boto3.dynamodb.conditions import Key
from sqlalchemy import asc, desc, func

from config import Config
from models.appendix import GlobalExam
from models.enums import NoHarmENV
from models.main import db
from models.segment import Exams, SegmentExam
from utils import aws


def get_exams_by_patient(idPatient: int, days: int):
    """Get exams by patient"""

    return (
        db.session.query(Exams)
        .filter(Exams.idPatient == idPatient)
        .filter(Exams.date >= (date.today() - timedelta(days=days)))
        .order_by(asc(Exams.typeExam), desc(Exams.date))
        .all()
    )


def get_exams_by_patient_from_dynamodb(schema: str, id_patient: int):
    """Get exams by patient from DynamoDB"""

    if Config.ENV == NoHarmENV.TEST.value:
        return []

    dynamodb = aws.get_resource("dynamodb", region_name="sa-east-1")
    table = dynamodb.Table("noharm_exame")

    PARTITION_KEY_VALUE = f"{schema}:{id_patient}"

    response = table.query(
        KeyConditionExpression=Key("schema_fkpessoa").eq(PARTITION_KEY_VALUE),
    )

    items = response.get("Items", [])

    return items


def get_next_exam_id(id_patient: int):
    """Generate a 13-digit exam ID with format: 9{id_patient}00000000"""

    patient_str = str(id_patient)
    patient_str = patient_str[-10:] if len(patient_str) > 10 else patient_str

    exam_id = "9" + patient_str + "0" * (12 - len(patient_str))
    mask = int(exam_id)

    total = (
        db.session.query(func.coalesce(func.max(Exams.idExame), mask).label("max"))
        .filter(Exams.idPatient == id_patient)
        .filter(Exams.idExame >= mask)
        .filter(Exams.created_by != None)
        .first()
    )
    if total:
        return total.max + 1

    return mask + 1


def get_exam_types():
    """Get all exam types"""
    return (
        db.session.query(SegmentExam.typeExam, func.max(SegmentExam.name).label("name"))
        .filter(SegmentExam.active == True)
        .group_by(SegmentExam.typeExam)
        .order_by("name")
        .all()
    )


def get_exams_reference(id_segment: int):
    """List all exams reference by segment"""
    exams = (
        SegmentExam.query.filter(SegmentExam.idSegment == id_segment)
        .filter(SegmentExam.active == True)
        .order_by(asc(SegmentExam.order))
        .all()
    )

    results = {}
    for e in exams:
        results[e.typeExam.lower()] = e
        if e.initials.lower().strip() == "creatinina":
            results["cr"] = e

    return results


def get_global_exams():
    """Get active global exams"""
    return (
        db.session.query(GlobalExam)
        .filter(GlobalExam.active)
        .order_by(GlobalExam.name.asc())
        .all()
    )


def get_infection_control_trigger_exams() -> dict[str, str]:
    """The exams the infection control exam triggers can watch: the active
    global exams flagged for them (public.exame), tpexame in lower case -> its
    name, by name"""
    rows = (
        db.session.query(GlobalExam.tp_exam, GlobalExam.name)
        .filter(GlobalExam.active == True)
        .filter(GlobalExam.infection_control_trigger == True)
        .order_by(GlobalExam.name.asc())
        .all()
    )
    return {tp_exam.lower(): name for tp_exam, name in rows}


def get_configured_exam_ref_types():
    """Get the reference exam types actually bound to active exams of this schema.

    A protocol variable of type exam_ref is matched at runtime against the
    tpexame_ref of the schema exams, not against the global catalog, so a
    globally valid tpexame that no active exam maps to never produces a result
    for this hospital.
    """
    return [
        r[0]
        for r in db.session.query(SegmentExam.tp_exam_ref)
        .filter(SegmentExam.active == True)
        .filter(SegmentExam.tp_exam_ref != None)
        .distinct()
        .all()
    ]


def get_exam_types_by_ref(exam_refs: set[str]) -> dict[str, str]:
    """The active exams of the schema mapped to these references
    (segmentoexame.tpexame_ref): tpexame -> its reference, both in lower case"""
    if not exam_refs:
        return {}

    rows = (
        db.session.query(SegmentExam.typeExam, SegmentExam.tp_exam_ref)
        .filter(SegmentExam.active == True)
        .filter(func.lower(SegmentExam.tp_exam_ref).in_(list(exam_refs)))
        .distinct()
        .all()
    )
    return {exam_type.lower(): exam_ref.lower() for exam_type, exam_ref in rows}


def get_creatinine_exam_types() -> set[str]:
    """The active exams of the schema that are the creatinine (abbreviation
    "creatinina", as get_exams_reference finds it), tpexame in lower case"""
    rows = (
        db.session.query(SegmentExam.typeExam)
        .filter(SegmentExam.active == True)
        .filter(func.lower(func.trim(SegmentExam.initials)) == "creatinina")
        .distinct()
        .all()
    )
    return {exam_type.lower() for (exam_type,) in rows}


def get_patient_results(
    id_patient: int,
    exam_types: set[str],
    until: datetime | None = None,
) -> list[Exams]:
    """The results of a patient for these exams (tpexame in lower case), oldest
    first, up to `until` when given. The table keeps the last days only (older
    results are archived in DynamoDB)"""
    if not exam_types:
        return []

    query = (
        db.session.query(Exams)
        .filter(Exams.idPatient == id_patient)
        .filter(func.lower(Exams.typeExam).in_(list(exam_types)))
        .filter(Exams.value != None)
    )
    if until is not None:
        query = query.filter(Exams.date <= until)

    return query.order_by(asc(Exams.date)).all()
