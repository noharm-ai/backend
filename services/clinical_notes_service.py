import json
import time
from datetime import datetime, timedelta
from sqlalchemy import text, Integer, func, desc, or_
from sqlalchemy.orm import undefer

from models.main import db, User, redis_client
from models.notes import ClinicalNotes
from models.prescription import Prescription, Patient
from models.enums import UserAuditTypeEnum
from services import memory_service, exams_service, user_service
from repository import clinical_notes_repository
from decorators.has_permission_decorator import has_permission, Permission
from exception.validation_error import ValidationError
from utils import status


@has_permission(Permission.WRITE_PRESCRIPTION)
def create_clinical_notes(data, user_context: User):
    if not memory_service.has_feature("PRIMARYCARE"):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    date = data.get("date", None)
    user_complete = db.session.query(User).get(user_context.id)
    cn = ClinicalNotes()

    cn.id = get_next_id(user_context.schema)
    cn.admissionNumber = data.get("admissionNumber", None)
    cn.date = datetime.today() if date == None else date
    cn.text = data.get("notes", None)
    cn.prescriber = user_complete.name
    cn.update = datetime.today()
    cn.user = user_context.id
    cn.position = (
        "Agendamento"
        if data.get("action", None) == "schedule"
        else data.get("tplName", "Farmacêutica")
    )
    cn.form = data.get("formValues", None)
    cn.template = data.get("template", None)

    db.session.add(cn)
    db.session.flush()

    # route data removed (it wasnt being used)

    return cn.id


def get_next_id(schema):
    result = db.session.execute(
        text("SELECT NEXTVAL('" + schema + ".evolucao_fkevolucao_seq')")
    )

    return ([row[0] for row in result])[0]


@has_permission(Permission.WRITE_PRESCRIPTION)
def remove_annotation(id_clinical_notes: int, annotation_type: str, user_context: User):
    """Removes allergies or dialysis annotations"""
    clinical_notes = (
        db.session.query(ClinicalNotes)
        .filter(ClinicalNotes.id == id_clinical_notes)
        .first()
    )
    if not clinical_notes:
        raise ValidationError(
            "Registro inválido", "errors.businessRules", status.HTTP_400_BAD_REQUEST
        )

    old_note = None
    if annotation_type == "allergy":
        old_note = clinical_notes.allergyText
        update = {"allergy": 0, "allergyText": None}
        db.session.query(ClinicalNotes).filter(
            ClinicalNotes.admissionNumber == clinical_notes.admissionNumber,
            ClinicalNotes.allergyText == old_note,
        ).update(update, synchronize_session="fetch")
        db.session.flush()

        refresh_allergies_cache(
            admission_number=clinical_notes.admissionNumber, user_context=user_context
        )
    elif annotation_type == "dialysis":
        old_note = clinical_notes.dialysisText
        update = {"dialysis": 0, "dialysisText": None}
        db.session.query(ClinicalNotes).filter(
            ClinicalNotes.admissionNumber == clinical_notes.admissionNumber,
            ClinicalNotes.dialysisText == old_note,
        ).update(update, synchronize_session="fetch")
        db.session.flush()

        refresh_dialysis_cache(
            admission_number=clinical_notes.admissionNumber, user_context=user_context
        )
    else:
        raise ValidationError(
            "Tipo inválido", "errors.businessRules", status.HTTP_400_BAD_REQUEST
        )

    # TODO: move to ClinicalNotesAudit
    user_service.create_audit(
        auditType=UserAuditTypeEnum.REMOVE_CLINICAL_NOTE_ANNOTATION,
        id_user=user_context.id,
        responsible=user_context,
        extra={
            "fkevolucao": id_clinical_notes,
            "notes": old_note,
            "type": annotation_type,
        },
    )


def get_tags():
    return [
        {"name": "dados", "column": "info", "key": "info"},
        {"name": "acesso", "column": None, "key": "access"},
        {"name": "germes", "column": None, "key": "germs"},
        {"name": "sinais", "column": "signs", "key": "signs"},
        {"name": "alergia", "column": "allergy", "key": "allergy"},
        {"name": "conduta", "column": "conduct", "key": "conduct"},
        {"name": "dialise", "column": "dialysis", "key": "dialysis"},
        {"name": "diliexc", "column": None, "key": "diliexc"},
        {"name": "doencas", "column": "diseases", "key": "diseases"},
        {"name": "resthid", "column": None, "key": "resthid"},
        {"name": "gestante", "column": None, "key": "pregnant"},
        {"name": "sintomas", "column": "symptoms", "key": "symptoms"},
        {"name": "complicacoes", "column": "complication", "key": "complication"},
        {"name": "medicamentos", "column": "medications", "key": "medications"},
        {"name": "paliativo", "column": None, "key": "palliative"},
        {"name": "medprevio", "column": None, "key": "prevdrug"},
    ]


@has_permission(Permission.READ_PRESCRIPTION)
def get_single_note(id_clinical_notes: int):
    cn = (
        db.session.query(ClinicalNotes)
        .filter(ClinicalNotes.id == id_clinical_notes)
        .first()
    )

    if not cn:
        raise ValidationError(
            "Registro inexistente",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    return convert_notes(notes=cn, has_primary_care=False, tags=[])


@has_permission(Permission.READ_PRESCRIPTION, Permission.READ_REGULATION)
def get_notes(admission_number: int, filter_date: str):
    has_primary_care = memory_service.has_feature("PRIMARYCARE")
    dates = None
    previous_admissions = []

    tags = get_tags()

    if filter_date is None:
        dates_query = (
            db.session.query(
                func.date(ClinicalNotes.date).label("date"),
                func.count().label("total"),
                func.array_agg(func.distinct(ClinicalNotes.position)).label("roles"),
            )
            .select_from(ClinicalNotes)
            .filter(ClinicalNotes.admissionNumber == admission_number)
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

            notes = get_notes_by_date(admission_number, dates_list, has_primary_care)
        else:
            notes = []

        admission = (
            db.session.query(Patient)
            .filter(Patient.admissionNumber == admission_number)
            .first()
        )

        if admission != None:
            admission_list = (
                db.session.query(Patient)
                .filter(Patient.idPatient == admission.idPatient)
                .order_by(desc(Patient.admissionDate))
                .limit(15)
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
        notes = get_notes_by_date(admission_number, [filter_date], has_primary_care)

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
        "dates": dateResults,
        "notes": noteResults,
        "previousAdmissions": previous_admissions,
    }


def get_notes_by_date(admission_number, dateList, has_primary_care):
    query = (
        ClinicalNotes.query.filter(ClinicalNotes.admissionNumber == admission_number)
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
    """Convert notes to a dictionary format"""

    max_length = 700000
    notes_text = notes.text
    if notes_text and len(notes_text) > max_length:
        notes_text = (
            notes_text[:max_length] + "<p>Evolução cortada por texto muito longo.</p>"
        )

    obj = {
        "id": str(notes.id),
        "admissionNumber": notes.admissionNumber,
        "text": notes_text,
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
                and (tag["name"] + "_count") in notes.annotations
                else 0
            )

    return obj


@has_permission(Permission.READ_PRESCRIPTION)
def get_user_last_clinical_notes(admission_number: int):
    last_notes = (
        db.session.query(Prescription.notes, Prescription.date)
        .filter(Prescription.admissionNumber == admission_number)
        .filter(Prescription.notes != None)
        .order_by(desc(Prescription.date))
        .first()
    )

    if last_notes:
        return {"text": last_notes.notes, "date": last_notes.date.isoformat()}

    return None


def get_count(admission_number: int, admission_date: datetime) -> int:
    cutoff_date = (
        datetime.today() - timedelta(days=120)
        if admission_date == None
        else admission_date - timedelta(days=1)
    )

    qNotes = (
        db.session.query(
            func.count().label("total"),
        )
        .select_from(ClinicalNotes)
        .filter(ClinicalNotes.admissionNumber == admission_number)
        .filter(ClinicalNotes.isExam == None)
        .filter(ClinicalNotes.date >= cutoff_date)
    )

    total = qNotes.scalar()

    return total


@has_permission(Permission.WRITE_PRESCRIPTION)
def update_note_text(id: int, data: dict, user_context: User):
    has_primary_care = memory_service.has_feature("PRIMARYCARE")

    n = db.session.query(ClinicalNotes).filter(ClinicalNotes.id == id).first()

    if n is None:
        raise ValidationError(
            "Registro inexistente",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    n.update = datetime.today()
    n.user = user_context.id

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

    return n


@has_permission(Permission.WRITE_PRESCRIPTION, Permission.MAINTAINER)
def refresh_clinical_notes_stats_cache(admission_number: int, user_context: User):
    def _add_cache(key: str, data: dict, expire_in: int):
        if data.get("data", None) != None:
            cache_data = {
                "dtevolucao": data.get("date", None),
                "fkevolucao": data.get("id", None),
                "lista": [data.get("data", None)],
            }

            redis_client.json().set(key, "$", cache_data)
            redis_client.expire(key, expire_in)

    # signs (expires in 30 days)
    signs = clinical_notes_repository.get_signs(
        admission_number=admission_number, user_context=user_context, cache=False
    )
    key = f"{user_context.schema}:{admission_number}:sinais"
    _add_cache(key=key, data=signs, expire_in=(30 * 24 * 60 * 60))

    # infos (expires in 30 days)
    infos = clinical_notes_repository.get_infos(
        admission_number=admission_number, user_context=user_context, cache=False
    )
    key = f"{user_context.schema}:{admission_number}:dados"
    _add_cache(key=key, data=infos, expire_in=(30 * 24 * 60 * 60))


@has_permission(Permission.WRITE_PRESCRIPTION, Permission.MAINTAINER)
def refresh_dialysis_cache(admission_number: int, user_context: User):
    dialysis = clinical_notes_repository.get_dialysis_cache(
        admission_number=admission_number
    )
    key = f"{user_context.schema}:{admission_number}:dialise"
    now = int(time.time())
    ten_days_ago = now - (10 * 24 * 60 * 60)

    redis_client.delete(key)

    for d in dialysis:
        if d.annotations:
            data = {
                "dtevolucao": d.date.isoformat(),
                "fkevolucao": d.id,
                "lista": d.annotations.get("dialise", []),
            }
            data_json = json.dumps(data)
            timestamp = int(
                time.mktime(time.strptime(data["dtevolucao"], "%Y-%m-%dT%H:%M:%S"))
            )
            redis_client.zadd(key, {data_json: timestamp})
            redis_client.zremrangebyscore(key, min=0, max=ten_days_ago)
            redis_client.expire(key, (10 * 24 * 60 * 60))  # 10 days


@has_permission(Permission.WRITE_PRESCRIPTION, Permission.MAINTAINER)
def refresh_allergies_cache(admission_number: int, user_context: User):
    allergies = clinical_notes_repository.get_allergies_cache(
        admission_number=admission_number
    )
    key = f"{user_context.schema}:{admission_number}:alergia"
    redis_client.delete(key)

    for a in allergies:
        if a.annotations:
            data = {
                "dtevolucao": a.date.isoformat(),
                "fkevolucao": a.id,
                "lista": a.annotations.get("allergiesComposed", []),
            }
            data_json = json.dumps(data)
            timestamp = int(
                time.mktime(time.strptime(data["dtevolucao"], "%Y-%m-%dT%H:%M:%S"))
            )
            redis_client.zadd(key, {data_json: timestamp})
            redis_client.expire(key, (120 * 24 * 60 * 60))  # 120 days
