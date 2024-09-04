import json
from utils import status
from sqlalchemy import asc, desc, func, between, text

from models.main import db
from models.appendix import *
from models.prescription import *
from models.notes import *
from models.enums import RoleEnum, GlobalMemoryEnum
from services import memory_service, prescription_agg_service
from exception.validation_error import ValidationError


def get_structured_info(admission_number, user, mock=False):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if RoleEnum.SUMMARY.value not in roles and RoleEnum.DOCTOR.value not in roles:
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

    draft = memory_service.get_memory(f"draft_summary_{admission_number}")

    engine = db.engines["report"]
    with engine.connect() as report_connection:
        data = {
            "patient": _get_patient_data(patient),
            "exams": _get_exams(
                id_patient=patient.idPatient,
                schema=user.schema,
                report_connection=report_connection,
            ),
            "allergies": _get_allergies(
                patient.idPatient, user.schema, report_connection
            ),
            "drugsUsed": _get_all_drugs_used(
                admission_number=admission_number,
                schema=user.schema,
                report_connection=report_connection,
            ),
            "drugsSuspended": _get_all_drugs_suspended(
                admission_number=admission_number,
                schema=user.schema,
                report_connection=report_connection,
            ),
            "receipt": _get_receipt(
                admission_number=admission_number,
                schema=user.schema,
                report_connection=report_connection,
            ),
            "summaryConfig": _get_summary_config(admission_number, mock),
            "draft": draft.value if draft else None,
        }

    return data


def _get_patient_data(patient: Patient):
    return {
        "idPatient": str(patient.idPatient),
        "admissionNumber": patient.admissionNumber,
        "admissionDate": (
            patient.admissionDate.isoformat() if patient.admissionDate else None
        ),
        "dischargeDate": (
            patient.dischargeDate.isoformat() if patient.dischargeDate else None
        ),
        "birthdate": patient.birthdate.isoformat() if patient.birthdate else None,
        "gender": patient.gender,
        "weight": patient.weight,
        "weightDate": patient.weightDate.isoformat() if patient.weightDate else None,
        "height": patient.height,
        "imc": (
            round((patient.weight / pow(patient.height / 100, 2)), 2)
            if patient.weight is not None and patient.height is not None
            else None
        ),
        "color": patient.skinColor,
    }


def _get_summary_config(admission_number, mock):
    summary_config = (
        db.session.query(GlobalMemory)
        .filter(GlobalMemory.kind == GlobalMemoryEnum.SUMMARY_CONFIG.value)
        .first()
    )
    summary_prompt = (
        db.session.query(GlobalMemory)
        .filter(GlobalMemory.kind == summary_config.value["prompt-config"])
        .first()
    )
    annotations = _get_all_annotations(
        admission_number,
        field_suffix=(
            "_text"
            if summary_config.value["prompt-config"] == "summary-prompt-sentence"
            else ""
        ),
    )

    config = [
        {"key": "reason"},
        {"key": "previousDrugs"},
        {"key": "diagnosis"},
        {"key": "dischargeCondition"},
        {"key": "dischargePlan"},
        {"key": "procedures"},
        {"key": "exams"},
        {"key": "clinicalSummary"},
    ]
    prompts = {}
    result = {}

    for c in config:
        key = c["key"]
        if mock:
            text = memory_service.get_memory(f"summary_text_{key}")
            prompts[key] = json.dumps(summary_prompt.value[key]).replace(
                ":replace_text", text.value["text"]
            )
        else:
            prompts[key] = json.dumps(summary_prompt.value[key]).replace(
                ":replace_text", annotations[key]["value"]
            )

        result[key] = {
            "prompt": json.loads(prompts[key]),
            "audit": annotations[key]["list"],
        }

    return result


def _get_all_annotations(admission_number, field_suffix=""):
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

    if first == None:
        empty = {"list": [], "value": ""}

        reason = empty
        previous_drugs = empty
        diagnosis = empty
        summary_annotation = empty
        discharge_plan = empty
        procedures = empty
        exams = empty
        discharge_condition = empty
        clinical_summary = empty
    else:
        reason = _get_annotation(
            admission_number=admission_number,
            field="motivo" + field_suffix,
            add=True,
            interval="4 DAYS",
            compare_date=first.date,
        )

        previous_drugs = _get_annotation(
            admission_number=admission_number,
            field="medprevio" + field_suffix,
            add=True,
            interval="1 DAY",
            compare_date=first.date,
        )

        diagnosis = _get_annotation(
            admission_number=admission_number,
            field="diagnostico" + field_suffix,
            add=True,
            interval=None,
            compare_date=None,
        )

        summary_annotation = _get_annotation(
            admission_number=admission_number,
            field="resumo" + field_suffix,
            add=False,
            interval="1 DAY",
            compare_date=last.date,
        )

        discharge_plan = _get_annotation(
            admission_number=admission_number,
            field="planoalta" + field_suffix,
            add=False,
            interval="1 DAY",
            compare_date=last.date,
        )

        procedures = _get_annotation(
            admission_number=admission_number,
            field="procedimentos" + field_suffix,
            add=True,
            interval=None,
            compare_date=None,
        )

        exams = _get_annotation(
            admission_number=admission_number,
            field="exames" + field_suffix,
            add=True,
            interval=None,
            compare_date=None,
        )

        discharge_condition = _get_annotation(
            admission_number=admission_number,
            field="condicaoalta" + field_suffix,
            add=False,
            interval="1 DAY",
            compare_date=last.date,
        )

        clinical_summary = {}
        clinical_summary["value"] = (
            reason["value"]
            + ". "
            + procedures["value"]
            + ". "
            + summary_annotation["value"]
        )[:1500]
        clinical_summary["list"] = (
            reason["list"] + procedures["list"] + summary_annotation["list"]
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

    uniqueList = set()
    for i in results:
        uniqueList.add(i[0])

    return {
        "value": ". ".join(uniqueList)[:2000].replace('"', '\\"'),
        "list": list(uniqueList),
    }


def _get_exams(id_patient, schema, report_connection):
    query = text(
        f"""
    select * from (
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
            s.posicao
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
    ) e
    where 
        posicao <= 30
    order by
        abrev    
    """
    )

    exams = report_connection.execute(query, {"id_patient": id_patient})

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


def _get_allergies(id_patient, schema, report_connection):
    query = text(
        f"""
    select
        distinct on (a.fkpessoa, coalesce (s.nome, a.nome_medicamento) )
        a.fkpessoa,
        coalesce (s.nome, a.nome_medicamento) nome
    from
        {schema}.alergia a
        left join {schema}.medicamento m on a.fkmedicamento = m.fkmedicamento
        left join public.substancia s on m.sctid = s.sctid
    where
        a.ativo is true
        and a.fkpessoa = :id_patient
    order by 1
    """
    )

    items = report_connection.execute(query, {"id_patient": id_patient})

    list = []
    for i in items:
        list.append(
            {
                "name": i[1],
            }
        )

    return list


def _get_all_drugs_used(admission_number, schema, report_connection):
    query = text(
        f"""
    select
        nome,
        idclasse,
        classe,
        fkmedicamento,
        case 
            when idclasse = 'J1' then (
                select 
                    string_agg(concat(to_char(coalesce(p.dtvigencia, p.dtprescricao) , 'DD/MM'), ' (', pm.fkfrequencia, ' x ', pm.dose, pm.fkunidademedida, ')'), ', ')
                from 
                    {schema}.presmed pm
                    inner join {schema}.prescricao p on (pm.fkprescricao = p.fkprescricao)
                where 
                    p.nratendimento = :admission_number
                    and pm.fkmedicamento = meds_classes.fkmedicamento
            )
            else null
        end as periodo,
        case 
            when idclasse = 'J1' then 0
            else 1
        end prioridade
    from (
        select
            nome,
            idclasse,
            classe,
            max(fkmedicamento) as fkmedicamento
        from (
            select 
                coalesce(s.nome, m.nome) as nome,
                coalesce (cm.idclasse, c.idclasse) as idclasse,
                coalesce (cm.nome, c.nome) as classe,
                pm.fkmedicamento
            from
                {schema}.presmed pm
                inner join {schema}.prescricao p on (pm.fkprescricao = p.fkprescricao)
                inner join {schema}.medicamento m on (pm.fkmedicamento = m.fkmedicamento)
                left join public.substancia s on (m.sctid = s.sctid)
                left join public.classe c on (s.idclasse = c.idclasse)
                left join public.classe cm on (c.idclassemae  = cm.idclasse)
            where 
                p.nratendimento = :admission_number
                and origem <> 'Dietas'
        ) meds
        group by
            nome, idclasse, classe
    ) meds_classes
    order by
        prioridade, classe, nome
    """
    )

    result = report_connection.execute(query, {"admission_number": admission_number})

    list = []
    for i in result:
        list.append({"name": i[0], "idClass": i[1], "nameClass": i[2], "period": i[4]})

    return list


def _get_all_drugs_suspended(admission_number, schema, report_connection):
    query = text(
        f"""
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
    )

    result = report_connection.execute(query, {"admission_number": admission_number})

    list = []
    for i in result:
        list.append(
            {
                "name": i[0],
            }
        )

    return list


def _get_receipt(admission_number, schema, report_connection):
    last_agg = prescription_agg_service.get_last_agg_prescription(admission_number)

    if last_agg == None:
        return []

    query = text(
        f"""
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
    )

    result = report_connection.execute(
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
