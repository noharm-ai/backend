import io
import pandas
from multiprocessing import Process, Manager
from datetime import datetime

from models.main import db
from models.appendix import *
from models.prescription import *
from routes.outlier_lib import add_score

FOLD_SIZE = 25


def prepare(id_drug, id_segment, user):
    history_count = (
        db.session.query(PrescriptionAgg)
        .filter(PrescriptionAgg.idDrug == id_drug)
        .filter(PrescriptionAgg.idSegment == id_segment)
        .count()
    )

    if history_count == 0:
        # add history if none found
        _add_prescription_history(
            id_drug=id_drug, id_segment=id_segment, schema=user.schema
        )

    # refresh history to update frequency and dose
    _refresh_agg(id_drug=id_drug, id_segment=id_segment, schema=user.schema)

    # refresh outliers
    return refresh_outliers(id_drug=id_drug, id_segment=id_segment, user=user)


def generate(id_drug, id_segment, fold, user):
    # call prepare before generate score
    # its not here for performance issues

    csv_buffer = _get_csv_buffer(
        id_segment=id_segment, schema=user.schema, id_drug=id_drug, fold=fold
    )

    manager = Manager()
    drugs = pandas.read_csv(csv_buffer)
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

    drugs_list = drugs["medication"].unique().astype(float)
    outliers = (
        Outlier.query.filter(Outlier.idSegment == id_segment)
        .filter(Outlier.idDrug.in_(drugs_list))
        .all()
    )

    new_os = pandas.DataFrame()

    for drug in poolDict:
        new_os = new_os.append(poolDict[drug])

    for o in outliers:
        no = new_os[
            (new_os["medication"] == o.idDrug)
            & (new_os["dose"] == o.dose)
            & (new_os["frequency"] == o.frequency)
        ]
        if len(no) > 0:
            o.score = no["score"].values[0]
            o.countNum = int(no["count"].values[0])
            o.update = datetime.today()
            o.user = user.id

            db.session.flush()


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
            and frequenciadia is not null and doseconv is not null
        
    """

    if id_drug != None:
        params["idDrug"] = id_drug
        query += " and fkmedicamento = :idDrug "

    query += f"""
        GROUP BY 
            idsegmento, fkmedicamento, ROUND(doseconv::numeric,2), frequenciadia
        ON CONFLICT DO nothing
    """

    return db.session.execute(query, params)


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
        params.apppend(FOLD_SIZE)
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


def _compute_outlier(idDrug, drugsItem, poolDict, fold):
    print("Starting...", fold, idDrug)
    poolDict[idDrug] = add_score(drugsItem)
    print("End...", fold, idDrug)


def _clean_outliers(id_drug, id_segment):
    q = db.session.query(Outlier).filter(Outlier.idSegment == id_segment)

    if id_drug != None:
        q = q.filter(Outlier.idDrug == id_drug)

    q.delete()


def _add_prescription_history(id_drug, id_segment, schema):
    query = f"""
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

    return db.session.execute(query, {"idSegment": id_segment, "idDrug": id_drug})


def _refresh_agg(id_drug, id_segment, schema):
    query = f"""
        insert into {schema}.prescricaoagg
        select * from {schema}.prescricaoagg where fkmedicamento = :idDrug and idsegmento = :idSegment
    """

    return db.session.execute(query, {"idSegment": id_segment, "idDrug": id_drug})
