from models.main import db, User
from models.segment import Exams
from exception.validation_error import ValidationError
from repository import exams_repository
from utils import dateutils, status
from decorators.has_permission_decorator import has_permission, Permission


@has_permission(Permission.READ_REPORTS)
def get_raw_exams(id_patient: int, user_context: User):
    if id_patient == None:
        raise ValidationError(
            "idPatient inválido",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    exams_list = exams_repository.get_exams_by_patient(id_patient, days=30)
    results = []

    for i in exams_list:
        exam: Exams = i
        results.append(
            {
                "idExam": exam.idExame,
                "typeExam": exam.typeExam,
                "idPatient": exam.idPatient,
                "admissionNumber": exam.admissionNumber,
                "dateExam": dateutils.to_iso(exam.date),
                "value": str(exam.value),
                "unit": exam.unit,
            }
        )
    return results
