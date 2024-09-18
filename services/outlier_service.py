import io
import pandas
from multiprocessing import Process, Manager
from datetime import datetime
from math import ceil
from sqlalchemy import text

from models.main import db
from models.appendix import *
from models.prescription import *
from models.enums import RoleEnum
from routes.outlier_lib import add_score
from exception.validation_error import ValidationError
from services.admin import admin_drug_service, admin_integration_status_service
from services import data_authorization_service, permission_service

FOLD_SIZE = 10


def prepare(id_drug, id_segment, user):
    def add_history_and_validate():
        history_count = add_prescription_history(
            id_drug=id_drug, id_segment=id_segment, schema=user.schema
        )

        if history_count == 0:
            raise ValidationError(
                "Este medicamento não possui histórico de prescrição no último ano. Por isso, não foi possível gerar escores.",
                "errors.invalidParams",
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
        _refresh_agg(id_drug=id_drug, id_segment=id_segment, schema=user.schema)

    # refresh outliers
    return refresh_outliers(id_drug=id_drug, id_segment=id_segment, user=user)


def generate(id_drug, id_segment, fold, user: User):
    # call prepare before generate score (only for wizard)
    start_date = datetime.now()

    if fold != None:
        if not permission_service.has_maintainer_permission(user):
            raise ValidationError(
                "Usuário não autorizado",
                "errors.unauthorizedUser",
                status.HTTP_401_UNAUTHORIZED,
            )

    if not data_authorization_service.has_segment_authorization(
        id_segment=id_segment, user=user
    ):
        raise ValidationError(
            "Usuário não autorizado neste segmento",
            "errors.businessRules",
            status.HTTP_401_UNAUTHORIZED,
        )

    csv_buffer = _get_csv_buffer(
        id_segment=id_segment, schema=user.schema, id_drug=id_drug, fold=fold
    )
    _log_perf(start_date, "GENERATE CSV BUFFER")

    start_date = datetime.now()

    manager = Manager()
    drugs = pandas.read_csv(csv_buffer)
    drugs_list = drugs["medication"].unique().astype(float)
    outliers = (
        Outlier.query.filter(Outlier.idSegment == id_segment)
        .filter(Outlier.idDrug.in_(drugs_list))
        .all()
    )

    _log_perf(start_date, "GET OUTLIERS LIST")

    start_date = datetime.now()

    with Manager() as manager:
        poolDict = manager.dict()

        processes = []
        for idDrug in drugs["medication"].unique():
            drugsItem = drugs[drugs["medication"] == idDrug]
            process = Process(
                target=_compute_outlier,
                args=(
                    idDrug,
                    drugsItem,
                    poolDict,
                    fold,
                ),
            )
            processes.append(process)

        for process in processes:
            process.start()

        for process in processes:
            process.join()

        new_os = pandas.DataFrame()

        for drug in poolDict:
            new_os = new_os.append(poolDict[drug])

    _log_perf(start_date, "PROCESS SCORES")

    start_date = datetime.now()

    updates = []
    for o in outliers:
        no = new_os[
            (new_os["medication"] == o.idDrug)
            & (new_os["dose"] == o.dose)
            & (new_os["frequency"] == o.frequency)
        ]
        if len(no) > 0:
            updates.append(
                _to_update_row(
                    {
                        "id": o.id,
                        "score": no["score"].values[0],
                        "countNum": int(no["count"].values[0]),
                    },
                    user,
                )
            )

    if len(updates) > 0:
        update_stmt = f"""
            with scores as (
                select * from (values {",".join(updates)}) AS t (idoutlier, score, countnum, update_at, update_by)
            )
            update {user.schema}.outlier o
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


def _compute_outlier(idDrug, drugsItem, poolDict, fold):
    print("Starting...", fold, idDrug)
    poolDict[idDrug] = add_score(drugsItem)
    print("End...", fold, idDrug)


def _clean_outliers(id_drug, id_segment):
    q = db.session.query(Outlier).filter(Outlier.idSegment == id_segment)

    if id_drug != None:
        q = q.filter(Outlier.idDrug == id_drug)

    q.delete()


def add_prescription_history(
    id_drug, id_segment, schema, clean=False, rollback_when_empty=False
):
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


def get_outliers_process_list(id_segment, user):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if RoleEnum.ADMIN.value not in roles and RoleEnum.TRAINING.value not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    pending_frequencies = admin_integration_status_service._get_pending_frequencies()
    if pending_frequencies > 0:
        raise ValidationError(
            "Existem frequências pendentes de conversão. Configure todas as frequências antes de gerar os escores.",
            "errors.business",
            status.HTTP_400_BAD_REQUEST,
        )

    print("Init Schema:", user.schema, "Segment:", id_segment)

    result = refresh_outliers(id_segment=id_segment, user=user)
    print("RowCount", result.rowcount)

    # fix inconsistencies after outlier insert
    admin_drug_service.fix_inconsistency(user)

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


def remove_outlier(id_drug, id_segment, user):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if RoleEnum.ADMIN.value not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

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
