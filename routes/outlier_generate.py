import io, os
import pandas as pd
from flask_api import status
from flask import Blueprint, request
from multiprocessing import Process, Manager
from models.main import *
from models.appendix import *
from models.prescription import *
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import text

from .outlier_lib import add_score
from services import outlier_service, drug_service
from exception.validation_error import ValidationError

app_gen = Blueprint("app_gen", __name__)
fold_size = 25


def compute_outlier(idDrug, drugsItem, poolDict, fold):
    print("Starting...", fold, idDrug)
    poolDict[idDrug] = add_score(drugsItem)
    print("End...", fold, idDrug)


@app_gen.route(
    "/outliers/generate/config/<int:id_segment>/<int:id_drug>", methods=["POST"]
)
@jwt_required()
def config(id_segment, id_drug):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"
    data = request.get_json()

    try:
        drug_service.drug_config_to_generate_score(
            id_drug=id_drug,
            id_segment=id_segment,
            id_measure_unit=data.get("idMeasureUnit", None),
            division=data.get("division", None),
            use_weight=data.get("useWeight", False),
            measure_unit_list=data.get("measureUnitList"),
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, True)


@app_gen.route(
    "/outliers/generate/prepare/<int:id_segment>/<int:id_drug>", methods=["POST"]
)
@jwt_required()
def prepare(id_segment, id_drug):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        result = outlier_service.prepare(
            id_drug=id_drug, id_segment=id_segment, user=user
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, result.rowcount)


@app_gen.route(
    "/outliers/generate/single/<int:id_segment>/<int:id_drug>", methods=["POST"]
)
@app_gen.route("/outliers/generate/fold/<int:id_segment>/<int:fold>", methods=["POST"])
@jwt_required()
def generate(id_segment, id_drug=None, fold=None):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        outlier_service.generate(
            id_drug=id_drug, id_segment=id_segment, fold=fold, user=user
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, True)


@app_gen.route(
    "/segments/<int:idSegment>/outliers/generate/fold/<int:fold>", methods=["GET"]
)
@app_gen.route(
    "/segments/<int:idSegment>/outliers/generate/drug/<int:idDrug>", methods=["GET"]
)
@jwt_required()
def generateOutliers(idSegment, fold=None, idDrug=None, clean=None):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    conn = db.engine.raw_connection()
    cursor = conn.cursor()

    query = (
        "SELECT fkmedicamento as medication, doseconv as dose, frequenciadia as frequency, contagem as count \
          FROM "
        + user.schema
        + ".outlier \
          WHERE idsegmento = "
        + str(int(idSegment))
    )

    if fold != None:
        query += (
            " AND fkmedicamento IN (\
                  SELECT fkmedicamento FROM "
            + user.schema
            + ".outlier\
                  WHERE idsegmento = "
            + str(int(idSegment))
            + "\
                  GROUP BY fkmedicamento\
                  ORDER BY fkmedicamento ASC\
                  LIMIT "
            + str(fold_size)
            + " OFFSET "
            + str((fold - 1) * fold_size)
            + ")"
        )

    if idDrug != None:
        query += " AND fkmedicamento = " + str(int(idDrug))

        if clean != None:
            queryDelete = (
                "DELETE FROM "
                + user.schema
                + ".outlier WHERE fkmedicamento = "
                + str(int(idDrug))
                + " AND idsegmento = "
                + str(int(idSegment))
                + ";"
            )
            result = db.engine.execute(queryDelete)
            print("RowCount Delete Drug", result.rowcount)

            refresh_agg = True
            drugAttribute = (
                db.session.query(DrugAttributes)
                .filter(DrugAttributes.idDrug == idDrug)
                .filter(DrugAttributes.idSegment == idSegment)
                .first()
            )
            if drugAttribute != None and drugAttribute.useWeight:
                refresh_agg = False

            if refresh_agg:
                queryRefresh = text(
                    f"""
                        insert into {user.schema}.prescricaoagg
                        select * from {user.schema}.prescricaoagg where fkmedicamento = :idDrug and idsegmento = :idSegment
                    """
                )

                result = db.engine.execute(
                    queryRefresh, {"idSegment": idSegment, "idDrug": idDrug}
                )
                print("RowCount Refresh Agg", result.rowcount)

        queryInsert = text(
            """
            INSERT INTO {schema}.outlier (idsegmento, fkmedicamento, doseconv, frequenciadia, contagem, escore, update_at)
                SELECT pagg.idsegmento, pagg.fkmedicamento, ROUND(pagg.doseconv::numeric,2) as doseconv, pagg.frequenciadia, SUM(pagg.contagem), NULL, now()
                FROM {schema}.prescricaoagg pagg
                WHERE pagg.idsegmento = :idSegment
                AND pagg.fkmedicamento = :idDrug and pagg.frequenciadia is not null and pagg.doseconv is not null
                GROUP BY pagg.idsegmento, pagg.fkmedicamento, ROUND(pagg.doseconv::numeric,2), pagg.frequenciadia
                ON CONFLICT DO nothing;
        """.format(
                schema=user.schema
            )
        )

        result = db.engine.execute(
            queryInsert, {"idSegment": idSegment, "idDrug": idDrug}
        )
        print("RowCount Insert Drug", result.rowcount)

        if clean != None and clean == 0:
            return {"status": "success"}, status.HTTP_200_OK

    print(query)

    outputquery = "COPY ({0}) TO STDOUT WITH CSV HEADER".format(query)

    csv_buffer = io.StringIO()
    cursor.copy_expert(outputquery, csv_buffer)
    csv_buffer.seek(0)

    manager = Manager()
    drugs = pd.read_csv(csv_buffer)
    poolDict = manager.dict()

    processes = []
    for idDrug in drugs["medication"].unique():
        drugsItem = drugs[drugs["medication"] == idDrug]
        process = Process(
            target=compute_outlier,
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

    idDrugs = drugs["medication"].unique().astype(float)
    outliers = (
        Outlier.query.filter(Outlier.idSegment == idSegment)
        .filter(Outlier.idDrug.in_(idDrugs))
        .all()
    )

    new_os = pd.DataFrame()
    print(
        "Appending Schema:",
        user.schema,
        "Segment:",
        idSegment,
        "Fold:",
        fold,
        "Drug",
        idDrug,
    )
    for drug in poolDict:
        new_os = new_os.append(poolDict[drug])

    print(
        "Updating Schema:",
        user.schema,
        "Segment:",
        idSegment,
        "Fold:",
        fold,
        "Drug",
        idDrug,
    )
    for o in outliers:
        no = new_os[
            (new_os["medication"] == o.idDrug)
            & (new_os["dose"] == o.dose)
            & (new_os["frequency"] == o.frequency)
        ]
        if len(no) > 0:
            o.score = no["score"].values[0]
            o.countNum = int(no["count"].values[0])

    print("Commiting Schema:", user.schema, "Segment:", idSegment, "Fold:", fold)
    db.session.commit()

    return {"status": "success"}, status.HTTP_200_OK


@app_gen.route(
    "/segments/<int:idSegment>/outliers/generate/drug/<int:idDrug>/clean/<int:clean>",
    methods=["POST"],
)
@jwt_required()
def outlierWizard(idSegment, idDrug, clean):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    data = request.get_json()

    division = data.get("division", None)
    idMeasureUnit = data.get("idMeasureUnit", None)
    useWeight = data.get("useWeight", False)
    measureUnitList = data.get("measureUnitList")

    if measureUnitList:
        if idMeasureUnit is None or len(idMeasureUnit) == 0:
            idMeasureUnit = measureUnitList[0]["idMeasureUnit"]

        for m in measureUnitList:
            setDrugUnit(idDrug, m["idMeasureUnit"], idSegment, m["fator"])

    drugAttr = DrugAttributes.query.get((idDrug, idSegment))

    newDrugAttr = False
    if drugAttr is None:
        newDrugAttr = True
        drugAttr = DrugAttributes()
        drugAttr.idDrug = idDrug
        drugAttr.idSegment = idSegment

    drugAttr.idMeasureUnit = idMeasureUnit
    drugAttr.division = division if division != 0 else None
    drugAttr.useWeight = useWeight
    drugAttr.update = datetime.today()
    drugAttr.user = user.id

    if newDrugAttr:
        db.session.add(drugAttr)

    db.session.commit()

    generateOutliers(idSegment, None, idDrug, clean)

    return {"status": "success"}, status.HTTP_200_OK


def setDrugUnit(idDrug, idMeasureUnit, idSegment, factor):
    u = MeasureUnitConvert.query.get((idMeasureUnit, idDrug, idSegment))
    new = False

    if u is None:
        new = True
        u = MeasureUnitConvert()
        u.idMeasureUnit = idMeasureUnit
        u.idDrug = idDrug
        u.idSegment = idSegment

    u.factor = factor

    if new:
        db.session.add(u)
