from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.main import User
from models.segment import Exams
from repository import exams_repository
from utils import dateutils, status


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
                "idExam": str(exam.idExame),
                "typeExam": exam.typeExam,
                "idPatient": str(exam.idPatient),
                "admissionNumber": str(exam.admissionNumber),
                "dateExam": dateutils.to_iso(exam.date),
                "value": str(exam.value),
                "unit": exam.unit,
            }
        )

        # from dynamo
        # results.append(
        #     {
        #         "idExam": i.get("fkexame"),
        #         "typeExam": i.get("tpexame"),
        #         "idPatient": i.get("fkpessoa"),
        #         "admissionNumber": "",
        #         "dateExam": dateutils.to_iso(i.get("dtexame")),
        #         "value": str(i.get("resultado")),
        #         "unit": i.get("unidade"),
        #     }
        # )
    return results
