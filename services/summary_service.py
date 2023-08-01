from flask_api import status

from models.main import db
from models.appendix import *
from models.prescription import *
from models.enums import RoleEnum, MemoryEnum
from services import memory_service
from exception.validation_error import ValidationError


def get_structured_info(admission_number, user):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    # bloqueio temporario
    if RoleEnum.SUPPORT.value not in roles and RoleEnum.ADMIN.value not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    patient = (
        db.session.query(Patient)
        .filter(Patient.admissionNumber == admission_number)
        .first()
    )

    if patient is None:
        raise ValidationError(
            "Registro inválido",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    exams = _get_exams(patient.idPatient, user.schema)

    summary_config = memory_service.get_memory(MemoryEnum.SUMMARY_CONFIG.value)

    return {
        "exams": exams,
        "allergies": None,
        "drugs": None,
        "summaryConfig": summary_config.value,
    }


def _get_exams(id_patient, schema):
    query = f"""
    select
        distinct on (e.fkpessoa,s.abrev)
        e.fkpessoa,
        s.abrev,
        resultado,
        dtexame,
        s.referencia,
        e.unidade,
        s.min,
        s.max,
        case
            when resultado < s.min then 'ABAIXO'
            when resultado > s.mAX then 'ACIMA'
            else 'DENTRO'
        end as referencia
    from
        {schema}.pessoa pe
    inner join {schema}.exame e on
        pe.fkpessoa = e.fkpessoa
    inner join {schema}.segmentoexame s on
        s.tpexame = lower(e.tpexame)
    where e.fkpessoa = :id_patient
    order by
        fkpessoa,
        abrev,
        dtexame desc
    """

    exams = db.session.execute(query, {"id_patient": id_patient})

    exams_list = []
    for e in exams:
        exams_list.append({"result": e[2]})

    return exams_list
