from flask_api import status
from models.main import *
from models.appendix import *
from models.prescription import *
from flask import Blueprint, request
from flask_jwt_extended import (
    jwt_required,
    get_jwt_identity,
)
from sqlalchemy import asc, func
from .utils import tryCommit
from datetime import date, datetime, timedelta

app_seg = Blueprint("app_seg", __name__)


@app_seg.route("/segments", methods=["GET"])
@jwt_required()
def getSegments():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    results = Segment.findAll()

    iList = []
    for i in results:
        iList.append({"id": i.id, "description": i.description, "status": i.status})

    return {"status": "success", "data": iList}, status.HTTP_200_OK


@app_seg.route("/segments/<int:idSegment>", methods=["GET"])
@app_seg.route("/segments/<int:idSegment>/<int:idHospital>", methods=["GET"])
@jwt_required()
def getSegmentsId(idSegment, idHospital=None):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    s = Segment.query.get(idSegment)

    sd = db.aliased(SegmentDepartment)
    q_department = (
        db.session.query(func.count(sd.id).label("count"))
        .select_from(sd)
        .filter(sd.idHospital == idHospital)
        .filter(sd.idDepartment == Department.id)
    )

    if idHospital != None:
        departments = (
            db.session.query(
                Department, SegmentDepartment, q_department.as_scalar().label("total")
            )
            .outerjoin(
                SegmentDepartment,
                and_(
                    SegmentDepartment.idDepartment == Department.id,
                    SegmentDepartment.idHospital == idHospital,
                    SegmentDepartment.id == idSegment,
                ),
            )
            .filter(Department.idHospital == idHospital)
            .order_by(asc(Department.name))
            .all()
        )
    else:
        departments = (
            db.session.query(
                Department, SegmentDepartment, literal_column("0").label("total")
            )
            .join(
                SegmentDepartment,
                and_(
                    SegmentDepartment.idDepartment == Department.id,
                    SegmentDepartment.idHospital == Department.idHospital,
                    SegmentDepartment.id == idSegment,
                ),
            )
            .order_by(asc(Department.name))
            .all()
        )

    segExams = (
        SegmentExam.query.filter(SegmentExam.idSegment == idSegment)
        .order_by(asc(SegmentExam.order))
        .all()
    )

    deps = []
    for d in departments:
        deps.append(
            {
                "idHospital": d[0].idHospital,
                "idDepartment": d[0].id,
                "name": d[0].name,
                "checked": d[1] is not None,
                "uses": d[2],
            }
        )

    exams = []
    for e in segExams:
        exams.append(
            {
                "type": e.typeExam.lower(),
                "initials": e.initials,
                "name": e.name,
                "min": e.min,
                "max": e.max,
                "ref": e.ref,
                "order": e.order,
                "active": e.active,
            }
        )

    return {
        "status": "success",
        "data": {
            "id": s.id if s else None,
            "idHospital": idHospital,
            "description": s.description if s else None,
            "status": s.status if s else None,
            "departments": deps,
            "exams": exams,
        },
    }, status.HTTP_200_OK


@app_seg.route("/departments", methods=["GET"])
@jwt_required()
def getDepartments():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    departs = Department.getAll()

    results = []
    for d in departs:
        results.append(
            {
                "idDepartment": d.id,
                "idHospital": d.idHospital,
                "name": d.name,
            }
        )

    return {"status": "success", "data": results}, status.HTTP_200_OK


@app_seg.route("/segments/exams/types", methods=["GET"])
@jwt_required()
def getCodes():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    typesExam = (
        db.session.query(Exams.typeExam)
        .filter(Exams.date > (date.today() - timedelta(days=30)))
        .group_by(Exams.typeExam)
        .order_by(asc(Exams.typeExam))
        .all()
    )

    results = ["mdrd", "ckd", "ckd21", "cg", "swrtz2"]
    for t in typesExam:
        results.append(t[0].lower())

    return {"status": "success", "data": {"types": results}}, status.HTTP_200_OK


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


@app_seg.route("/segments/<int:idSegment>/exams", methods=["PUT"])
@jwt_required()
def setExams(idSegment):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    data = request.get_json()
    typeExam = data.get("type", None)

    segExam = SegmentExam.query.get((idSegment, typeExam))

    newSegExam = False
    if segExam is None:
        newSegExam = True
        segExam = SegmentExam()
        segExam.idSegment = idSegment
        segExam.typeExam = typeExam

    if "initials" in data.keys():
        segExam.initials = data.get("initials", None)
    if "name" in data.keys():
        segExam.name = data.get("name", None)
    if "min" in data.keys():
        segExam.min = data.get("min", None)
    if "max" in data.keys():
        segExam.max = data.get("max", None)
    if "ref" in data.keys():
        segExam.ref = data.get("ref", None)
    if "order" in data.keys():
        segExam.order = data.get("order", None)
    if "active" in data.keys():
        segExam.active = bool(data.get("active", False))

    segExam.update = datetime.today()
    segExam.user = user.id

    if newSegExam:
        db.session.add(segExam)

    return tryCommit(db, typeExam)


@app_seg.route("/segments/<int:idSegment>/exams-order", methods=["PUT"])
@jwt_required()
def setExamsOrder(idSegment):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    data = request.get_json()

    examsOrder = data.get("exams", None)
    if not examsOrder:
        return {
            "status": "error",
            "message": "Sem exames para ordenar!",
        }, status.HTTP_400_BAD_REQUEST

    segExams = (
        SegmentExam.query.filter(SegmentExam.idSegment == idSegment)
        .order_by(asc(SegmentExam.order))
        .all()
    )

    result = {}
    for s in segExams:
        if s.typeExam in examsOrder:
            s.order = examsOrder.index(s.typeExam)
        result[s.typeExam] = s.order

    return tryCommit(db, result)
