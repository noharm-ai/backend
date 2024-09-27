from flask import Blueprint
from flask_jwt_extended import (
    jwt_required,
)
from sqlalchemy import asc

from utils import status
from models.main import db, dbSession
from models.prescription import Segment, SegmentExam
from services import segment_service
from decorators.api_endpoint_decorator import api_endpoint

app_seg = Blueprint("app_seg", __name__)


@app_seg.route("/segments", methods=["GET"])
@api_endpoint()
def getSegments():
    results = segment_service.get_segments()

    list = []
    for i in results:
        list.append({"id": i.id, "description": i.description, "status": i.status})

    return list


@app_seg.route("/segments/departments", methods=["GET"])
@api_endpoint()
def get_segment_departments():
    return segment_service.get_segment_departments()


# TODO: refactor
@app_seg.route("/segments/exams/refs", methods=["GET"])
@jwt_required()
def getRefs():
    dbSession.setSchema("hsc_test")

    refs = (
        db.session.query(SegmentExam, Segment)
        .join(Segment, Segment.id == SegmentExam.idSegment)
        .filter(SegmentExam.idSegment.in_([1, 3]))
        .order_by(asc(Segment.id), asc(SegmentExam.name))
        .all()
    )

    results = []
    for r in refs:
        results.append(
            {
                "segment": r[1].description,
                "type": r[0].typeExam,
                "name": r[0].name,
                "initials": r[0].initials,
                "ref": r[0].ref,
                "min": r[0].min,
                "max": r[0].max,
                "order": r[0].order,
            }
        )

    return {"status": "success", "data": results}, status.HTTP_200_OK
