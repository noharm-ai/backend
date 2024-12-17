from models.main import db, User
from models.segment import Exams
from exception.validation_error import ValidationError
from repository.reports.reports_exams_search_repository import get_exams_by_patient
from utils import dateutils, status
from decorators.has_permission_decorator import has_permission, Permission


@has_permission(Permission.READ_REPORTS)
def get_exams(id_patient: int, user_context: User):
    if id_patient == None:
        raise ValidationError(
            "idPatient inválido",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    else:
        exams_list = get_exams_by_patient(id_patient, days=30)
        results = []

        for i in exams_list:
            exam: Exams = i
            results.append(
                {
                    "idExame": str(exam.idExame),
                    "typeExam": str(exam.typeExam),
                    "idPatient": str(exam.idPatient),
                    "admissionNumber": str(exam.admissionNumber),
                    "dateExam": dateutils.to_iso(exam.date),
                    "value": str(exam.value),
                    "unit": exam.unit,
                }
            )
        return results
