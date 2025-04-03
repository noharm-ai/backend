"""Service: outlier related operations"""

import io
import json
import logging
from datetime import datetime
from math import ceil
from typing import List
from decimal import Decimal, ROUND_HALF_UP

import boto3
from sqlalchemy import text, func, distinct, and_, or_, asc, literal, literal_column

from models.main import (
    db,
    User,
    PrescriptionAgg,
    Outlier,
    Drug,
    Substance,
    DrugAttributes,
)
from models.appendix import Notes, MeasureUnit, MeasureUnitConvert
from exception.validation_error import ValidationError
from services.admin import admin_drug_service, admin_integration_status_service
from services import data_authorization_service, substance_service
from decorators.has_permission_decorator import has_permission, Permission
from utils import prescriptionutils, numberutils, stringutils, examutils, status
from config import Config

FOLD_SIZE = 10


@has_permission(Permission.WRITE_DRUG_SCORE)
def prepare(id_drug, id_segment, user_context: User):
    """step 1: prepare records to generate score. Refresh history and outliers"""

    def add_history_and_validate():
        history_count = add_prescription_history(
            id_drug=id_drug, id_segment=id_segment, user_context=user_context
        )

        if history_count == 0:
            raise ValidationError(
                "Este medicamento não possui histórico de prescrição no último ano. Por isso, não foi possível gerar escores.",
                "errors.invalidParams",
                status.HTTP_400_BAD_REQUEST,
            )

    if not data_authorization_service.has_segment_authorization(
        id_segment=id_segment, user=user_context
    ):
        raise ValidationError(
            "Usuário não autorizado neste segmento",
            "errors.businessRules",
            status.HTTP_401_UNAUTHORIZED,
        )

    history_count = (
        db.session.query(PrescriptionAgg)
        .filter(PrescriptionAgg.idDrug == id_drug)
        .filter(PrescriptionAgg.idSegment == id_segment)
        .filter(PrescriptionAgg.frequency != None)
        .filter(PrescriptionAgg.doseconv != None)
        .filter(PrescriptionAgg.dose > 0)
        .count()
    )

    if history_count == 0:
        # add history if none found
        add_history_and_validate()

    elif history_count > 20000:
        # clean and insert again
        db.session.query(PrescriptionAgg).filter(
            PrescriptionAgg.idDrug == id_drug
        ).filter(PrescriptionAgg.idSegment == id_segment).delete()

        add_history_and_validate()

    else:
        # refresh history to update frequency and dose
        _refresh_agg(id_drug=id_drug, id_segment=id_segment, schema=user_context.schema)

    # refresh outliers
    return refresh_outliers(id_drug=id_drug, id_segment=id_segment, user=user_context)


@has_permission(Permission.WRITE_DRUG_SCORE, Permission.WRITE_SEGMENT_SCORE)
def generate(
    id_drug, id_segment, fold, user_context: User, user_permissions: List[Permission]
):
    # call prepare before generate score (only for wizard)
    start_date = datetime.now()

    if fold != None:
        if Permission.WRITE_SEGMENT_SCORE not in user_permissions:
            raise ValidationError(
                "Usuário não autorizado",
                "errors.unauthorizedUser",
                status.HTTP_401_UNAUTHORIZED,
            )

    if not data_authorization_service.has_segment_authorization(
        id_segment=id_segment, user=user_context
    ):
        raise ValidationError(
            "Usuário não autorizado neste segmento",
            "errors.businessRules",
            status.HTTP_401_UNAUTHORIZED,
        )

    csv_buffer = _get_csv_buffer(
        id_segment=id_segment, schema=user_context.schema, id_drug=id_drug, fold=fold
    )
    csv_string = csv_buffer.getvalue()

    if csv_string.count("\n") < 2:
        # list has only a header line, abort score generation
        return False

    _log_perf(start_date, "GENERATE CSV BUFFER")

    start_date = datetime.now()

    lambda_client = boto3.client("lambda", region_name=Config.NIFI_SQS_QUEUE_REGION)
    response = lambda_client.invoke(
        FunctionName=Config.SCORES_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(
            {
                "command": "lambda_scores.generate_scores",
                "csv_string": csv_string,
            }
        ),
    )

    scores = json.loads(json.loads(response["Payload"].read().decode("utf-8")))

    _log_perf(start_date, "PROCESS SCORES")

    start_date = datetime.now()

    updates = []
    drugs_list = list(scores.keys())
    outliers = (
        Outlier.query.filter(Outlier.idSegment == id_segment)
        .filter(Outlier.idDrug.in_(drugs_list))
        .all()
    )

    def _get_drug_score(id_drug: int, dose: float, frequency: int):
        drug_scores = scores[str(id_drug)]

        return next(
            sc
            for sc in drug_scores
            if sc["dose"] == dose and sc["frequency"] == frequency
        )

    for o in outliers:
        no = _get_drug_score(id_drug=o.idDrug, dose=o.dose, frequency=o.frequency)

        if len(no) > 0:
            updates.append(
                _to_update_row(
                    {
                        "id": o.id,
                        "score": no["score"],
                        "countNum": int(no["count"]),
                    },
                    user_context,
                )
            )

    if len(updates) > 0:
        update_stmt = f"""
            with scores as (
                select * from (values {",".join(updates)}) AS t (idoutlier, score, countnum, update_at, update_by)
            )
            update {user_context.schema}.outlier o
            set 
                contagem = s.countnum,
                escore = s.score,
                update_at = s.update_at,
                update_by = s.update_by
            from
                scores s
            where 
                s.idoutlier = o.idoutlier
        """

        db.session.execute(text(update_stmt))

        _log_perf(start_date, "UPDATE SCORES")


def _to_update_row(update: dict, user: User):
    return f"""({update["id"]}, {update["score"]}, {update["countNum"]}, '{datetime.today().isoformat()}'::timestamp, {user.id})"""


def refresh_outliers(id_segment, user, id_drug=None):
    # clean old outliers
    _clean_outliers(id_drug=id_drug, id_segment=id_segment)

    # insert new ones
    params = {
        "idSegment": id_segment,
        "idUser": user.id,
        "currentDate": datetime.today(),
    }
    query = f"""
        INSERT INTO {user.schema}.outlier 
            (idsegmento, fkmedicamento, doseconv, frequenciadia, contagem, update_at, update_by)
        SELECT 
            idsegmento, fkmedicamento, ROUND(doseconv::numeric,2) as doseconv, frequenciadia, SUM(contagem), :currentDate, :idUser
        FROM
            {user.schema}.prescricaoagg
        WHERE 
            idsegmento = :idSegment
            and frequenciadia is not null and doseconv is not null and dose > 0
        
    """

    if id_drug != None:
        params["idDrug"] = id_drug
        query += " and fkmedicamento = :idDrug "

    query += f"""
        GROUP BY 
            idsegmento, fkmedicamento, ROUND(doseconv::numeric,2), frequenciadia
        ON CONFLICT DO nothing
    """

    return db.session.execute(text(query), params)


def _get_csv_buffer(id_segment, schema, id_drug=None, fold=None):
    params = [id_segment]
    query = f"""
        SELECT 
            fkmedicamento as medication, doseconv as dose, frequenciadia as frequency, contagem as count
        FROM
            {schema}.outlier
        WHERE 
            idsegmento = %s
    """

    if id_drug != None:
        params.append(id_drug)
        query += " and fkmedicamento = %s "
    else:
        params.append(id_segment)
        params.append(FOLD_SIZE)
        params.append((fold - 1) * FOLD_SIZE)
        query += f""" 
            and fkmedicamento IN (
                SELECT fkmedicamento 
                FROM {schema}.outlier
                WHERE 
                    idsegmento = %s
                GROUP BY fkmedicamento
                ORDER BY fkmedicamento ASC
                LIMIT %s
                OFFSET %s
            )
        """

    outputquery = "COPY ({0}) TO STDOUT WITH CSV HEADER".format(query)

    conn = db.engine.raw_connection()
    cursor = conn.cursor()
    copy_query = cursor.mogrify(outputquery, tuple(params))

    csv_buffer = io.StringIO()
    cursor.copy_expert(copy_query, csv_buffer)
    csv_buffer.seek(0)

    return csv_buffer


def _log_perf(start_date, section):
    end_date = datetime.now()
    logging.basicConfig()
    logger = logging.getLogger("noharm.backend")

    logger.debug(f"PERF {section}: {(end_date-start_date).total_seconds()}")


def _clean_outliers(id_drug, id_segment):
    q = db.session.query(Outlier).filter(Outlier.idSegment == id_segment)

    if id_drug != None:
        q = q.filter(Outlier.idDrug == id_drug)

    q.delete()


@has_permission(Permission.MAINTAINER)
def add_prescription_history(
    id_drug, id_segment, user_context: User, clean=False, rollback_when_empty=False
):
    schema = user_context.schema

    if clean:
        db.session.query(PrescriptionAgg).filter(
            PrescriptionAgg.idDrug == id_drug
        ).filter(PrescriptionAgg.idSegment == id_segment).delete()

    query = text(
        f"""
        INSERT INTO 
            {schema}.prescricaoagg 
            (
                fkhospital,fksetor, idsegmento, fkmedicamento, 
                fkunidademedida, fkfrequencia, dose, doseconv, 
                frequenciadia, peso, contagem
            ) 
        SELECT 
            p.fkhospital, 
            p.fksetor, 
            p.idsegmento, 
            fkmedicamento, 
            fkunidademedida, 
            f.fkfrequencia, 
            dose, 
            dose, 
            coalesce(f.frequenciadia , pm.frequenciadia), 
            coalesce(ps.peso, 999), 
            count(*)
        FROM 
            {schema}.presmed pm
            inner join {schema}.prescricao p on pm.fkprescricao = p.fkprescricao
            left join {schema}.frequencia f on f.fkfrequencia = pm.fkfrequencia
            left join {schema}.pessoa ps on (p.nratendimento = ps.nratendimento and p.fkpessoa = ps.fkpessoa)
        where 
            p.dtprescricao > now() - interval '1 year'
            and p.idsegmento = :idSegment
            and pm.fkmedicamento = :idDrug
            and pm.dose is not null
            and pm.frequenciadia is not null 
        group by 
            1,2,3,4,5,6,7,8,9,10
    """
    )

    db.session.execute(query, {"idSegment": id_segment, "idDrug": id_drug})

    count = (
        db.session.query(PrescriptionAgg)
        .filter(PrescriptionAgg.idDrug == id_drug)
        .filter(PrescriptionAgg.idSegment == id_segment)
        .count()
    )

    if rollback_when_empty and count == 0:
        raise ValidationError(
            "Este medicamento não foi prescrito no último ano neste segmento",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    return count


def _refresh_agg(id_drug, id_segment, schema):
    query = text(
        f"""
        insert into {schema}.prescricaoagg
        select * from {schema}.prescricaoagg where fkmedicamento = :idDrug and idsegmento = :idSegment
    """
    )

    return db.session.execute(query, {"idSegment": id_segment, "idDrug": id_drug})


@has_permission(Permission.WRITE_SEGMENT_SCORE)
def get_outliers_process_list(id_segment, user_context: User):
    pending_frequencies = admin_integration_status_service._get_pending_frequencies()
    if pending_frequencies > 0:
        raise ValidationError(
            "Existem frequências pendentes de conversão. Configure todas as frequências antes de gerar os escores.",
            "errors.business",
            status.HTTP_400_BAD_REQUEST,
        )

    print("Init Schema:", user_context.schema, "Segment:", id_segment)

    result = refresh_outliers(id_segment=id_segment, user=user_context)
    print("RowCount", result.rowcount)

    # fix inconsistencies after outlier insert
    admin_drug_service.fix_inconsistency()

    totalCount = (
        db.session.query(func.count(distinct(Outlier.idDrug)))
        .select_from(Outlier)
        .filter(Outlier.idSegment == id_segment)
        .scalar()
    )
    folds = ceil(totalCount / FOLD_SIZE)
    print("Total Count:", totalCount, folds)

    processesUrl = []

    for fold in range(1, folds + 1):
        processesUrl.append(
            {
                "url": f"/outliers/generate/fold/{str(int(id_segment))}/{str(fold)}",
                "method": "POST",
                "params": {},
            }
        )

    return processesUrl


@has_permission(Permission.WRITE_SEGMENT_SCORE)
def remove_outlier(id_drug, id_segment):
    count = (
        db.session.query(PrescriptionAgg)
        .filter(PrescriptionAgg.idDrug == id_drug)
        .filter(PrescriptionAgg.idSegment == id_segment)
        .count()
    )

    if count > 0:
        raise ValidationError(
            "Não é possível remover este outlier, pois possui histórico de prescrição.",
            "errors.invalid",
            status.HTTP_400_BAD_REQUEST,
        )

    db.session.query(Outlier).filter(Outlier.idDrug == id_drug).filter(
        Outlier.idSegment == id_segment
    ).delete()


@has_permission(Permission.READ_PRESCRIPTION)
def get_outliers_list(
    id_segment: int, id_drug: int, user_context: User, frequency=None, dose=None
):
    outliers = (
        db.session.query(Outlier, Notes)
        .outerjoin(Notes, Notes.idOutlier == Outlier.id)
        .filter(Outlier.idSegment == id_segment, Outlier.idDrug == id_drug)
        .order_by(Outlier.countNum.desc(), Outlier.frequency.asc())
        .all()
    )
    d = (
        db.session.query(Drug, Substance)
        .outerjoin(Substance, Substance.id == Drug.sctid)
        .filter(Drug.id == id_drug)
        .first()
    )

    drug: Drug = d.Drug if d else None
    substance: Substance = d.Substance if d else None

    drugAttr = (
        db.session.query(DrugAttributes)
        .filter(DrugAttributes.idDrug == id_drug)
        .filter(DrugAttributes.idSegment == id_segment)
        .first()
    )

    relations = []
    defaultNote = None
    if drug and drug.sctid:
        relations = substance_service.get_substance_relations(sctid=drug.sctid)

    if drugAttr is None:
        drugAttr = DrugAttributes()

    if dose:
        if drugAttr.division and dose:
            dose = round(
                ceil(((float(dose)) / drugAttr.division)) * drugAttr.division, 2
            )
        else:
            rounded = Decimal(dose).quantize(Decimal("1e-2"), rounding=ROUND_HALF_UP)
            dose = rounded

    units = get_drug_outlier_units(id_drug=id_drug, id_segment=id_segment)
    defaultUnit = "unlikely big name for a measure unit"
    bUnit = False
    for unit in units:
        if unit["fator"] == 1 and len(unit["idMeasureUnit"]) < len(defaultUnit):
            defaultUnit = unit["idMeasureUnit"]
            bUnit = True

    if not bUnit:
        defaultUnit = ""

    newOutlier = True
    results = []
    for o in outliers:
        selected = False
        if (
            dose is not None
            and frequency is not None
            and numberutils.is_float(dose)
            and numberutils.is_float(frequency)
        ):
            if float(dose) == o[0].dose and float(frequency) == o[0].frequency:
                newOutlier = False
                selected = True

        results.append(
            {
                "idOutlier": o[0].id,
                "idDrug": o[0].idDrug,
                "countNum": o[0].countNum,
                "dose": o[0].dose,
                "unit": defaultUnit,
                "frequency": prescriptionutils.freqValue(o[0].frequency),
                "score": o[0].score,
                "manualScore": o[0].manualScore,
                "obs": o[1].notes if o[1] != None else "",
                "updatedAt": o[0].update.isoformat() if o[0].update else None,
                "selected": selected,
            }
        )

    if (
        dose is not None
        and frequency is not None
        and newOutlier
        and numberutils.is_float(dose)
        and numberutils.is_float(frequency)
    ):
        o = Outlier()
        o.idDrug = id_drug
        o.idSegment = id_segment
        o.countNum = 1
        o.dose = float(dose)
        o.frequency = float(frequency)
        o.score = 4
        o.manualScore = None
        o.update = datetime.today()
        o.user = user_context.id

        db.session.add(o)
        db.session.flush()

        results.append(
            {
                "idOutlier": o.id,
                "idDrug": id_drug,
                "countNum": 1,
                "dose": float(dose),
                "unit": defaultUnit,
                "frequency": prescriptionutils.freqValue(float(frequency)),
                "score": 4,
                "manualScore": None,
                "obs": "",
                "updatedAt": o.update.isoformat() if o.update else None,
                "selected": True,
            }
        )

    return {
        "outliers": results,
        "antimicro": drugAttr.antimicro,
        "mav": drugAttr.mav,
        "controlled": drugAttr.controlled,
        "notdefault": drugAttr.notdefault,
        "maxDose": drugAttr.maxDose,
        "kidney": drugAttr.kidney,
        "liver": drugAttr.liver,
        "platelets": drugAttr.platelets,
        "elderly": drugAttr.elderly,
        "tube": drugAttr.tube,
        "division": drugAttr.division,
        "useWeight": drugAttr.useWeight,
        "idMeasureUnit": drugAttr.idMeasureUnit or defaultUnit,
        "idMeasureUnitPrice": drugAttr.idMeasureUnitPrice,
        "amount": drugAttr.amount,
        "amountUnit": drugAttr.amountUnit,
        "price": drugAttr.price,
        "maxTime": drugAttr.maxTime,
        "whiteList": drugAttr.whiteList,
        "chemo": drugAttr.chemo,
        "sctidA": str(drug.sctid) if d else "",
        "sctNameA": stringutils.strNone(substance.name).upper() if substance else "",
        "substance": {
            "divisionRange": substance.division_range if substance else None,
            "unit": substance.default_measureunit if substance else None,
        },
        "relations": relations,
        "relationTypes": [
            {"key": t, "value": examutils.typeRelations[t]}
            for t in examutils.typeRelations
        ],
        "defaultNote": defaultNote,
    }


@has_permission(Permission.READ_PRESCRIPTION)
def get_drug_outlier_units(id_drug: int, id_segment: int):
    u = db.aliased(MeasureUnit)
    p = db.aliased(PrescriptionAgg)
    mu = db.aliased(MeasureUnitConvert)
    d = db.aliased(Drug)

    units = (
        db.session.query(
            u.id,
            u.description,
            d.name,
            func.sum(func.coalesce(p.countNum, 0)).label("count"),
            func.max(mu.factor).label("factor"),
        )
        .select_from(u)
        .join(d, and_(d.id == id_drug))
        .outerjoin(
            p,
            and_(
                p.idMeasureUnit == u.id, p.idDrug == id_drug, p.idSegment == id_segment
            ),
        )
        .outerjoin(
            mu,
            and_(
                mu.idMeasureUnit == u.id,
                mu.idDrug == id_drug,
                mu.idSegment == id_segment,
            ),
        )
        .filter(or_(p.idSegment == id_segment, mu.idSegment == id_segment))
        .group_by(u.id, u.description, p.idMeasureUnit, d.name)
        .order_by(asc(u.description))
        .all()
    )

    results = []
    for u in units:
        results.append(
            {
                "idMeasureUnit": u.id,
                "description": u.description,
                "drugName": u[2],
                "fator": u[4] if u[4] != None else 1,
                "contagem": u[3],
            }
        )

    return results


@has_permission(Permission.WRITE_DRUG_SCORE)
def update_outlier(id_outlier: int, data: dict, user_context: User):
    o = db.session.query(Outlier).filter(Outlier.id == id_outlier).first()

    if "manualScore" in data:
        manualScore = data.get("manualScore", None)
        o.manualScore = manualScore
        o.update = datetime.today()
        o.user = user_context.id

    if "obs" in data:
        notes = data.get("obs", None)
        obs = db.session.query(Notes).filter(Notes.idOutlier == id_outlier).first()
        newObs = False

        if obs is None:
            newObs = True
            obs = Notes()
            obs.idOutlier = id_outlier
            obs.idPrescriptionDrug = 0
            obs.idSegment = o.idSegment
            obs.idDrug = o.idDrug
            obs.dose = o.dose
            obs.frequency = o.frequency

        obs.notes = notes
        obs.update = datetime.today()
        obs.user = user_context.id

        if newObs:
            db.session.add(obs)

    return o


@has_permission(Permission.READ_PRESCRIPTION)
def get_outlier_drugs(
    id_segment: int, term: str = None, id_drug: List[int] = [], add_substance=False
):
    if add_substance:
        query_drug = db.session.query(
            Drug.id, Drug.name.label("name"), literal("drug").label("r_type")
        ).filter(Drug.source.is_distinct_from("SUBNH"))
        query_substance = db.session.query(
            Substance.id,
            Substance.name.label("name"),
            literal("substance").label("r_type"),
        ).filter(Substance.active == True)

        query = query_drug.union(query_substance).filter(
            literal_column("name").ilike("%" + str(term) + "%")
        )

        results = query.order_by(literal_column("name")).all()
    else:
        segDrubs = (
            db.session.query(Outlier.idDrug.label("idDrug"))
            .filter(Outlier.idSegment == id_segment)
            .group_by(Outlier.idDrug)
            .subquery()
        )

        if id_segment != None:
            drugs = Drug.query.filter(Drug.id.in_(segDrubs))
        else:
            drugs = db.session.query(Drug)

        if term:
            drugs = drugs.filter(Drug.name.ilike("%" + str(term) + "%"))

        if len(id_drug) > 0:
            drugs = drugs.filter(Drug.id.in_(id_drug))

        results = drugs.order_by(asc(Drug.name)).all()

    items = []
    for d in results:
        items.append(
            {
                "idDrug": str(d.id),
                "name": d.name,
            }
        )

    return items
