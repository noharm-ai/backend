from sqlalchemy import text, desc

from models.main import db
from models.appendix import *
from models.prescription import *
from models.notes import ClinicalNotes
from services import memory_service, data_authorization_service

from exception.validation_error import ValidationError


def create_exam(
    admission_number, id_prescription, id_patient, type_exam, value, unit, user
):
    if not memory_service.has_feature("PRIMARYCARE"):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    exam = Exams()
    exam.idExame = get_next_id(user.schema)
    exam.idPatient = id_patient
    exam.idPrescription = id_prescription
    exam.admissionNumber = admission_number
    exam.date = datetime.today()
    exam.typeExam = type_exam
    exam.value = value
    exam.unit = unit

    db.session.add(exam)
    db.session.flush()


def get_next_id(schema):
    result = db.session.execute(
        text("SELECT NEXTVAL('" + schema + ".exame_fkexame_seq')")
    )

    return ([row[0] for row in result])[0]


def upsert_seg_exam(data: dict, id_segment: int, user: User):
    if id_segment == None:
        raise ValidationError(
            "Parametros inválidos",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if not data_authorization_service.has_segment_authorization(
        id_segment=id_segment, user=user
    ):
        raise ValidationError(
            "Usuário não autorizado neste segmento",
            "errors.businessRules",
            status.HTTP_401_UNAUTHORIZED,
        )

    typeExam = data.get("type", None)
    segExam = (
        db.session.query(SegmentExam)
        .filter(SegmentExam.idSegment == id_segment)
        .filter(SegmentExam.typeExam == typeExam)
        .first()
    )

    newSegExam = False
    if segExam is None:
        newSegExam = True
        segExam = SegmentExam()
        segExam.idSegment = id_segment
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

    return segExam


def exams_reorder(exams, id_segment, user: User):
    if not exams:
        raise ValidationError(
            "Parametros inválidos",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if not data_authorization_service.has_segment_authorization(
        id_segment=id_segment, user=user
    ):
        raise ValidationError(
            "Usuário não autorizado neste segmento",
            "errors.businessRules",
            status.HTTP_401_UNAUTHORIZED,
        )

    segExams = (
        SegmentExam.query.filter(SegmentExam.idSegment == id_segment)
        .order_by(asc(SegmentExam.order))
        .all()
    )

    result = {}
    for s in segExams:
        if s.typeExam in exams:
            s.order = exams.index(s.typeExam)
            db.session.flush()

        result[s.typeExam] = s.order

    return result


def get_textual_exams(admission_number: int = None, id_patient: int = None):
    admission_number_array = []

    if admission_number != None:
        admission_number_array.append(admission_number)
    else:
        admissions = (
            db.session.query(Patient)
            .filter(Patient.idPatient == id_patient)
            .order_by(desc(Patient.admissionDate))
            .limit(5)
            .all()
        )

        for a in admissions:
            admission_number_array.append(a.admissionNumber)

    if len(admission_number_array) == 0:
        return []

    return (
        ClinicalNotes.query.filter(
            ClinicalNotes.admissionNumber.in_(admission_number_array)
        )
        .filter(ClinicalNotes.isExam == True)
        .filter(ClinicalNotes.text != None)
        .filter(ClinicalNotes.date > (datetime.today() - timedelta(days=90)))
        .order_by(desc(ClinicalNotes.date))
        .all()
    )
