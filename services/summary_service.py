import json
from flask_api import status

from models.main import db
from models.appendix import *
from models.prescription import *
from models.enums import RoleEnum, MemoryEnum
from services import memory_service, prescription_agg_service
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

    return {
        "patient": _get_patient_data(patient),
        "exams": _get_exams(patient.idPatient, user.schema),
        "allergies": None,
        "drugsUsed": _get_all_drugs_used(
            admission_number=admission_number, schema=user.schema
        ),
        "drugsSuspended": _get_all_drugs_suspended(
            admission_number=admission_number, schema=user.schema
        ),
        "receipt": _get_receipt(admission_number=admission_number, schema=user.schema),
        "summaryConfig": _get_summary_config(),
    }


def _get_patient_data(patient: Patient):
    return {
        "idPatient": patient.idPatient,
        "admissionNumber": patient.admissionNumber,
        "admissionDate": patient.admissionDate.isoformat()
        if patient.admissionDate
        else None,
        "dischargeDate": patient.dischargeDate.isoformat()
        if patient.dischargeDate
        else None,
        "birthdate": patient.birthdate.isoformat() if patient.birthdate else None,
        "gender": patient.gender,
        "weight": patient.weight,
        "height": patient.height,
        "imc": round((patient.weight / pow(patient.height / 100, 2)), 2)
        if patient.weight is not None and patient.height is not None
        else None,
        "color": patient.skinColor,
    }


def _get_summary_config():
    summary_config = memory_service.get_memory(MemoryEnum.SUMMARY_CONFIG.value)
    # temporary source
    reason = memory_service.get_memory("summary_text1")
    previous_drugs = memory_service.get_memory("summary_text2")
    diagnosis = memory_service.get_memory("summary_text_diagnosis")
    discharge_condition = memory_service.get_memory("summary_text_dischargeCondition")
    procedures = memory_service.get_memory("summary_text_procedures")

    reason_payload = json.dumps(summary_config.value["reason"]).replace(
        ":replace_text", reason.value["text"]
    )

    previous_drugs_payload = json.dumps(summary_config.value["previousDrugs"]).replace(
        ":replace_text", previous_drugs.value["text"]
    )

    diagnosis_payload = json.dumps(summary_config.value["diagnosis"]).replace(
        ":replace_text", diagnosis.value["text"]
    )

    discharge_condition_payload = json.dumps(
        summary_config.value["dischargeCondition"]
    ).replace(":replace_text", discharge_condition.value["text"])

    procedures_payload = json.dumps(summary_config.value["procedures"]).replace(
        ":replace_text", procedures.value["text"]
    )

    return {
        "url": summary_config.value["url"],
        "apikey": summary_config.value["apikey"],
        "reason": json.loads(reason_payload),
        "previousDrugs": json.loads(previous_drugs_payload),
        "diagnosis": json.loads(diagnosis_payload),
        "dischargeCondition": json.loads(discharge_condition_payload),
        "procedures": json.loads(procedures_payload),
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
        s.max
    from
        {schema}.pessoa pe
    inner join {schema}.exame e on
        pe.fkpessoa = e.fkpessoa
    inner join {schema}.segmentoexame s on
        s.tpexame = lower(e.tpexame)
    where 
        e.fkpessoa = :id_patient
        and (resultado < s.min or resultado > s.max)
    order by
        fkpessoa,
        abrev,
        dtexame desc
    """

    exams = db.session.execute(query, {"id_patient": id_patient})

    exams_list = []
    for e in exams:
        exams_list.append(
            {
                "name": e[1],
                "date": e[3].isoformat() if e[3] else None,
                "result": e[2],
                "measureUnit": e[5],
            }
        )

    return exams_list


def _get_all_drugs_used(admission_number, schema):
    query = f"""
    select 
        distinct(coalesce(s.nome, m.nome)) as nome
    from
        {schema}.presmed pm
        inner join {schema}.prescricao p on (pm.fkprescricao = p.fkprescricao)
        inner join {schema}.medicamento m on (pm.fkmedicamento = m.fkmedicamento)
        left join public.substancia s on (m.sctid = s.sctid)
    where 
        p.nratendimento = :admission_number
        and origem <> 'Dietas'
    order by
        nome
    """

    result = db.session.execute(query, {"admission_number": admission_number})

    list = []
    for i in result:
        list.append(
            {
                "name": i[0],
            }
        )

    return list


def _get_all_drugs_suspended(admission_number, schema):
    query = f"""
    select 
        distinct(coalesce(s.nome, m.nome)) as nome
    from
        {schema}.presmed pm
        inner join {schema}.prescricao p on (pm.fkprescricao = p.fkprescricao)
        inner join {schema}.medicamento m on (pm.fkmedicamento = m.fkmedicamento)
        left join public.substancia s on (m.sctid = s.sctid)
    where 
        p.nratendimento = :admission_number
        and pm.origem <> 'Dietas'
        and pm.dtsuspensao is not null 
        and (
            select count(*)
            from {schema}.presmed pm2
                inner join {schema}.prescricao p2 on (pm2.fkprescricao = p2.fkprescricao)
            where 
                p2.nratendimento = p.nratendimento 
                and pm2.fkprescricao > pm.fkprescricao
                and pm2.fkmedicamento = pm.fkmedicamento
                and pm2.dtsuspensao is null 
        ) = 0
    order by
        nome
    """

    result = db.session.execute(query, {"admission_number": admission_number})

    list = []
    for i in result:
        list.append(
            {
                "name": i[0],
            }
        )

    return list


def _get_receipt(admission_number, schema):
    last_agg = prescription_agg_service.get_last_agg_prescription(admission_number)

    if last_agg == None:
        return []

    query = f"""
    select distinct on (nome_med, frequencia, dose, fkunidademedida, via) * from (
        select 
            m.nome as nome_med, p.dtprescricao, f.nome as frequencia , pm.dose, pm.fkunidademedida, pm.via
        from
            {schema}.presmed pm
            inner join {schema}.prescricao p on (pm.fkprescricao = p.fkprescricao)
            inner join {schema}.medicamento m on (pm.fkmedicamento = m.fkmedicamento)
            left join {schema}.frequencia f on (pm.fkfrequencia = f.fkfrequencia)
        where 
            p.nratendimento = :admission_number
            and pm.origem <> 'Dietas'
            and date(:date) between p.dtprescricao::date and p.dtvigencia 
            and pm.dtsuspensao is null
        order by
            nome_med, p.dtprescricao desc
    ) receita
    """

    result = db.session.execute(
        query, {"admission_number": admission_number, "date": last_agg.date}
    )

    list = []
    for i in result:
        list.append(
            {
                "name": i[0],
                "frequency": i[2],
                "dose": i[3],
                "measureUnit": i[4],
                "route": i[5],
            }
        )

    return list
