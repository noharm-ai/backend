import os
from models.main import db, dbSession, User
from models.notes import ClinicalNotes
from models.prescription import Patient
from flask import Blueprint, request
from markupsafe import escape as escape_html
from utils import status
from flask_jwt_extended import jwt_required, get_jwt_identity
from .utils import tryCommit
from sqlalchemy import desc, or_, func, Integer
from sqlalchemy.orm import undefer
from datetime import datetime
from services import clinical_notes_service, memory_service

from exception.validation_error import ValidationError

app_note = Blueprint("app_note", __name__)


@app_note.route("/notes/<int:admissionNumber>/v2", methods=["GET"])
@jwt_required()
def get_notes_v2(admissionNumber):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    has_primary_care = memory_service.has_feature("PRIMARYCARE")
    filter_date = request.args.get("date", None)
    dates = None
    previous_admissions = []

    tags = [
        {"name": "dados", "column": "info"},
        {"name": "acesso", "column": None},
        {"name": "germes", "column": None},
        {"name": "sinais", "column": "signs"},
        {"name": "alergia", "column": "allergy"},
        {"name": "conduta", "column": "conduct"},
        {"name": "dialise", "column": "dialysis"},
        {"name": "diliexc", "column": None},
        {"name": "doencas", "column": "diseases"},
        {"name": "resthid", "column": None},
        {"name": "gestante", "column": None},
        {"name": "sintomas", "column": "symptoms"},
        {"name": "complicacoes", "column": "complication"},
        {"name": "medicamentos", "column": "medications"},
    ]

    if filter_date is None:
        dates_query = (
            db.session.query(
                func.date(ClinicalNotes.date).label("date"),
                func.count().label("total"),
                func.array_agg(func.distinct(ClinicalNotes.position)).label("roles"),
            )
            .select_from(ClinicalNotes)
            .filter(ClinicalNotes.admissionNumber == admissionNumber)
            .filter(or_(ClinicalNotes.isExam == None, ClinicalNotes.isExam == False))
            .group_by(func.date(ClinicalNotes.date))
            .order_by(desc(func.date(ClinicalNotes.date)))
        )

        for tag in tags:
            if tag["column"] != None:
                dates_query = dates_query.add_columns(
                    func.sum(getattr(ClinicalNotes, tag["column"])).label(tag["name"])
                )
            else:
                column_name = tag["name"] + "_count"
                dates_query = dates_query.add_columns(
                    func.sum(
                        func.cast(
                            func.coalesce(
                                ClinicalNotes.annotations[column_name].astext, "0"
                            ),
                            Integer,
                        )
                    ).label(tag["name"])
                )

        dates = dates_query.all()

        if len(dates) > 0:
            dates_list = []
            for row in range(3):
                if len(dates) > row:
                    dates_list.append(dates[row][0])

            notes = get_notes_by_date(admissionNumber, dates_list, has_primary_care)
        else:
            notes = []

        admission = (
            db.session.query(Patient)
            .filter(Patient.admissionNumber == admissionNumber)
            .first()
        )

        if admission != None:
            admission_list = (
                db.session.query(Patient)
                .filter(Patient.idPatient == admission.idPatient)
                .filter(Patient.admissionNumber < admissionNumber)
                .order_by(desc(Patient.admissionDate))
                .limit(10)
                .all()
            )

            for pa in admission_list:
                previous_admissions.append(
                    {
                        "admissionNumber": pa.admissionNumber,
                        "admissionDate": (
                            pa.admissionDate.isoformat() if pa.admissionDate else None
                        ),
                        "dischargeDate": (
                            pa.dischargeDate.isoformat() if pa.dischargeDate else None
                        ),
                    }
                )
    else:
        notes = get_notes_by_date(admissionNumber, [filter_date], has_primary_care)

    noteResults = []
    for n in notes:
        noteResults.append(convert_notes(n, has_primary_care, tags))

    dateResults = []
    if dates is not None:
        for d in dates:
            d_dict = {"date": d.date.isoformat(), "count": d.total, "roles": d.roles}

            for tag in tags:
                if tag["column"] != None:
                    d_dict[tag["column"]] = getattr(d, tag["name"])
                else:
                    d_dict[tag["name"]] = getattr(d, tag["name"])

            dateResults.append(d_dict)

    return {
        "status": "success",
        "data": {
            "dates": dateResults,
            "notes": noteResults,
            "previousAdmissions": previous_admissions,
        },
    }, status.HTTP_200_OK


def get_notes_by_date(admissionNumber, dateList, has_primary_care):
    query = (
        ClinicalNotes.query.filter(ClinicalNotes.admissionNumber == admissionNumber)
        .filter(or_(ClinicalNotes.isExam == None, ClinicalNotes.isExam == False))
        .filter(func.date(ClinicalNotes.date).in_(dateList))
    )

    query = query.options(undefer(ClinicalNotes.annotations))

    if has_primary_care:
        query = query.options(
            undefer(ClinicalNotes.form), undefer(ClinicalNotes.template)
        )

    return query.order_by(desc(ClinicalNotes.date)).all()


def convert_notes(notes, has_primary_care, tags):
    obj = {
        "id": str(notes.id),
        "admissionNumber": notes.admissionNumber,
        "text": notes.text,
        "form": notes.form if has_primary_care else None,
        "template": notes.template if has_primary_care else None,
        "date": notes.date.isoformat(),
        "prescriber": notes.prescriber,
        "position": notes.position,
    }

    for tag in tags:
        if tag["column"] != None:
            obj[tag["column"]] = getattr(notes, tag["column"])
        else:
            obj[tag["name"]] = (
                notes.annotations[tag["name"] + "_count"]
                if notes.annotations != None
                else 0
            )

    return obj


@app_note.route("/notes/<int:idNote>", methods=["POST"])
@jwt_required()
def changeNote(idNote):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    has_primary_care = memory_service.has_feature("PRIMARYCARE")
    data = request.get_json()

    if not ClinicalNotes.exists():
        return {
            "status": "error",
            "message": "Schema não tem evolução!",
        }, status.HTTP_400_BAD_REQUEST

    n = ClinicalNotes.query.get(idNote)

    if n is None:
        return {
            "status": "error",
            "message": "Evolução Inexistente!",
        }, status.HTTP_400_BAD_REQUEST

    n.update = datetime.today()
    n.user = user.id

    if "text" in data.keys():
        n.text = data.get("text", None)
        n.medications = n.text.count("annotation-medicamentos")
        n.complication = n.text.count("annotation-complicacoes")
        n.symptoms = n.text.count("annotation-sintomas")
        n.diseases = n.text.count("annotation-doencas")
        n.info = n.text.count("annotation-dados")
        n.conduct = n.text.count("annotation-conduta")
        n.signs = n.text.count("annotation-sinais")
        n.allergy = n.text.count("annotation-alergia")
        n.names = n.text.count("annotation-nomes")

    if has_primary_care:
        if "date" in data.keys() and data.get("date", None) != None:
            n.date = data.get("date")

        if "form" in data.keys() and data.get("form", None) != None:
            n.form = data.get("form")

    return tryCommit(db, escape_html(idNote))


@app_note.route("/notes", methods=["POST"])
@jwt_required()
def create():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        id = clinical_notes_service.create_clinical_notes(data, user)
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, id, user.permission())


@app_note.route("/notes/remove-annotation", methods=["POST"])
@jwt_required()
def remove_annotation():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        clinical_notes_service.remove_annotation(
            id_clinical_notes=data.get("idClinicalNotes", None),
            annotation_type=data.get("annotationType", None),
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, True, user.permission())
