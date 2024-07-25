from sqlalchemy import text, Integer, func, desc
from sqlalchemy.orm import undefer

from models.main import db
from models.appendix import *
from models.notes import ClinicalNotes
from models.prescription import *
from models.enums import UserAuditTypeEnum
from services import memory_service, exams_service, permission_service, user_service

from exception.validation_error import ValidationError


def create_clinical_notes(data, user):
    if not memory_service.has_feature("PRIMARYCARE"):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    date = data.get("date", None)
    user_complete = db.session.query(User).get(user.id)
    cn = ClinicalNotes()

    cn.id = get_next_id(user.schema)
    cn.admissionNumber = data.get("admissionNumber", None)
    cn.date = datetime.today() if date == None else date
    cn.text = data.get("notes", None)
    cn.prescriber = user_complete.name
    cn.update = datetime.today()
    cn.user = user.id
    cn.position = (
        "Agendamento"
        if data.get("action", None) == "schedule"
        else data.get("tplName", "Farmacêutica")
    )
    cn.form = data.get("formValues", None)
    cn.template = data.get("template", None)

    db.session.add(cn)
    db.session.flush()

    # route data
    if cn.template != None:
        prescription = Prescription.query.get(data.get("idPrescription"))

        for group in cn.template:
            for q in group["questions"]:
                if "integration" in q:
                    if (
                        q["integration"]["to"] == "exams"
                        and q["id"] in cn.form
                        and cn.form[q["id"]] != None
                    ):
                        exams_service.create_exam(
                            admission_number=data.get("admissionNumber", None),
                            id_prescription=prescription.id,
                            id_patient=prescription.idPatient,
                            type_exam=q["id"],
                            value=cn.form[q["id"]],
                            unit=q["integration"]["unit"],
                            user=user,
                        )

    return cn.id


def get_next_id(schema):
    result = db.session.execute(
        text("SELECT NEXTVAL('" + schema + ".evolucao_fkevolucao_seq')")
    )

    return ([row[0] for row in result])[0]


def remove_annotation(id_clinical_notes: int, annotation_type: str, user: User):
    if not permission_service.is_pharma(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    clinical_notes = (
        db.session.query(ClinicalNotes)
        .filter(ClinicalNotes.id == id_clinical_notes)
        .first()
    )
    if clinical_notes == None:
        raise ValidationError(
            "Registro inválido", "errors.businessRules", status.HTTP_400_BAD_REQUEST
        )

    old_note = None
    if annotation_type == "allergy":
        old_note = clinical_notes.allergyText
        clinical_notes.allergy = 0
        clinical_notes.allergyText = None
    elif annotation_type == "dialysis":
        old_note = clinical_notes.dialysisText
        clinical_notes.dialysis = 0
        clinical_notes.dialysisText = None
    else:
        raise ValidationError(
            "Tipo inválido", "errors.businessRules", status.HTTP_400_BAD_REQUEST
        )

    user_service.create_audit(
        auditType=UserAuditTypeEnum.REMOVE_CLINICAL_NOTE_ANNOTATION,
        id_user=user.id,
        responsible=user,
        extra={
            "fkevolucao": id_clinical_notes,
            "notes": old_note,
            "type": annotation_type,
        },
    )


def get_tags():
    return [
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
                .filter(Patient.admissionNumber < admission_number)
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
