from sqlalchemy import text

from models.main import db
from models.appendix import *
from models.prescription import *
from services import memory_service

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
