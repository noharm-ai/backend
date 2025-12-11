"""Repository: exams related operations"""

from datetime import date, timedelta

import boto3
from boto3.dynamodb.conditions import Key
from sqlalchemy import asc, desc, func

from models.main import db
from models.segment import Exams, SegmentExam


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

    dynamodb = boto3.resource("dynamodb", region_name="sa-east-1")
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
