from sqlalchemy import text

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
