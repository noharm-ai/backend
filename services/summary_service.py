import json
from flask_api import status
from sqlalchemy import asc, desc, func, between

from models.main import db
from models.appendix import *
from models.prescription import *
from models.notes import *
from models.enums import RoleEnum, MemoryEnum
from services import memory_service, prescription_agg_service
from exception.validation_error import ValidationError


def get_structured_info(admission_number, user, mock=False):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if (
        RoleEnum.SUPPORT.value not in roles
        and RoleEnum.ADMIN.value not in roles
        and RoleEnum.DOCTOR.value not in roles
    ):
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
        "summaryConfig": _get_summary_config(admission_number, mock),
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


def _get_summary_config(admission_number, mock):
    summary_config = memory_service.get_memory(MemoryEnum.SUMMARY_CONFIG.value)
    # temporary source
    annotations = _get_all_annotations(admission_number)

    if mock:
        reason = memory_service.get_memory("summary_text1")
        previous_drugs = memory_service.get_memory("summary_text2")
        diagnosis = memory_service.get_memory("summary_text_diagnosis")
        discharge_condition = memory_service.get_memory(
            "summary_text_dischargeCondition"
        )
        discharge_plan = memory_service.get_memory("summary_text_dischargePlan")
        procedures = memory_service.get_memory("summary_text_procedures")
        exams = memory_service.get_memory("summary_text_exams")

    reason_payload = json.dumps(summary_config.value["reason"]).replace(
        ":replace_text", reason.value["text"] if mock else annotations["reason"]
    )

    previous_drugs_payload = json.dumps(summary_config.value["previousDrugs"]).replace(
        ":replace_text",
        previous_drugs.value["text"] if mock else annotations["previousDrugs"],
    )

    diagnosis_payload = json.dumps(summary_config.value["diagnosis"]).replace(
        ":replace_text", diagnosis.value["text"] if mock else annotations["diagnosis"]
    )

    discharge_condition_payload = json.dumps(
        summary_config.value["dischargeCondition"]
    ).replace(
        ":replace_text",
        discharge_condition.value["text"]
        if mock
        else annotations["dischargeCondition"],
    )

    discharge_plan_payload = json.dumps(summary_config.value["dischargePlan"]).replace(
        ":replace_text",
        discharge_plan.value["text"] if mock else annotations["dischargePlan"],
    )

    procedures_payload = json.dumps(summary_config.value["procedures"]).replace(
        ":replace_text", procedures.value["text"] if mock else annotations["procedures"]
    )

    exams_payload = json.dumps(summary_config.value["exams"]).replace(
        ":replace_text", exams.value["text"] if mock else annotations["exams"]
    )

    return {
        "url": summary_config.value["url"],
        "apikey": summary_config.value["apikey"],
        "reason": json.loads(reason_payload),
        "previousDrugs": json.loads(previous_drugs_payload),
        "diagnosis": json.loads(diagnosis_payload),
        "dischargeCondition": json.loads(discharge_condition_payload),
        "dischargePlan": json.loads(discharge_plan_payload),
        "procedures": json.loads(procedures_payload),
        "exams": json.loads(exams_payload),
    }


def _get_all_annotations(admission_number):
    first = (
        db.session.query(ClinicalNotes)
        .filter(ClinicalNotes.admissionNumber == admission_number)
        .order_by(asc(ClinicalNotes.date))
        .first()
    )
    last = (
        db.session.query(ClinicalNotes)
        .filter(ClinicalNotes.admissionNumber == admission_number)
        .order_by(desc(ClinicalNotes.date))
        .first()
    )

    reason = _get_annotation(
        admission_number=admission_number,
        field="motivo",
        add=True,
        interval="1 DAY",
        compare_date=first.date,
    )

    previous_drugs = _get_annotation(
        admission_number=admission_number,
        field="medprevio",
        add=True,
        interval="1 DAY",
        compare_date=first.date,
    )

    diagnosis = _get_annotation(
        admission_number=admission_number,
        field="diagnostico",
        add=True,
        interval=None,
        compare_date=None,
    )

    clinical_summary = _get_annotation(
        admission_number=admission_number,
        field="resumo",
        add=False,
        interval="1 DAY",
        compare_date=last.date,
    )

    discharge_plan = _get_annotation(
        admission_number=admission_number,
        field="planoalta",
        add=False,
        interval="1 DAY",
        compare_date=last.date,
    )

    procedures = _get_annotation(
        admission_number=admission_number,
        field="procedimentos",
        add=True,
        interval=None,
        compare_date=None,
    )

    exams = _get_annotation(
        admission_number=admission_number,
        field="exames",
        add=True,
        interval=None,
        compare_date=None,
    )

    discharge_condition = _get_annotation(
        admission_number=admission_number,
        field="condicaoalta",
        add=False,
        interval="1 DAY",
        compare_date=last.date,
    )

    return {
        "reason": reason,
        "previousDrugs": previous_drugs,
        "diagnosis": diagnosis,
        "clinicalSummary": clinical_summary,
        "dischargePlan": discharge_plan,
        "procedures": procedures,
        "exams": exams,
        "dischargeCondition": discharge_condition,
    }


def _get_annotation(admission_number, field, add, interval, compare_date):
    query = (
        db.session.query(func.jsonb_array_elements_text(ClinicalNotes.summary[field]))
        .select_from(ClinicalNotes)
        .filter(ClinicalNotes.admissionNumber == admission_number)
    )

    if compare_date:
        if add:
            query = query.filter(
                between(
                    func.date(ClinicalNotes.date),
                    func.date(compare_date),
                    func.date(compare_date) + func.cast(interval, INTERVAL),
                )
            )
        else:
            query = query.filter(
                between(
                    func.date(ClinicalNotes.date),
                    func.date(compare_date) - func.cast(interval, INTERVAL),
                    func.date(compare_date),
                )
            )

    results = query.order_by(ClinicalNotes.date).all()

    list = []
    for i in results:
        list.append(i[0])

    return ". ".join(list)[:1500]


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
