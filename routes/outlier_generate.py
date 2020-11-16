import gzip, requests, io
from flask_api import status
from flask import Blueprint, request
from multiprocessing import Process, Manager
from models.main import *
from models.appendix import *
from models.prescription import *
from flask_jwt_extended import (jwt_required, get_jwt_identity, get_raw_jwt, create_access_token)
from config import Config
import pandas as pd
from sqlalchemy import distinct, func
from math import ceil
from .outlier_lib import add_score

app_gen = Blueprint('app_gen',__name__)
fold_size = 25

def compute_outlier(idDrug, drugsItem, poolDict, fold):
    print('Starting...', fold, idDrug)
    poolDict[idDrug] = add_score(drugsItem)
    print('End...', fold, idDrug)


@app_gen.route("/segments/<int:idSegment>/outliers/generate", methods=['GET'])
@jwt_required
def callOutliers(idSegment):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    auth_token = create_access_token(get_jwt_identity())
    header = {'Authorization': 'Bearer ' + auth_token}

    conn = db.engine.raw_connection()
    cursor = conn.cursor()

    print('Init Schema:', user.schema, 'Segment:', idSegment)

    query = "INSERT INTO " + user.schema + ".outlier (idsegmento, fkmedicamento, doseconv, frequenciadia, contagem)\
            SELECT idsegmento, fkmedicamento, ROUND(doseconv::numeric,2) as doseconv, frequenciadia, SUM(contagem)\
            FROM " + user.schema + ".prescricaoagg\
            WHERE idsegmento = " + str(int(idSegment)) + " and frequenciadia is not null and doseconv is not null\
            GROUP BY idsegmento, fkmedicamento, ROUND(doseconv::numeric,2), frequenciadia\
            ON CONFLICT DO nothing;"

    result = db.engine.execute(query)
    print('RowCount', result.rowcount)

    totalCount = db.session.query(func.count(distinct(Outlier.idDrug)))\
                .select_from(Outlier)\
                .filter(Outlier.idSegment == idSegment)\
                .scalar()
    folds = ceil(totalCount / fold_size)
    print('Total Count:', totalCount, folds)

    processesUrl = []
    for fold in range(1,folds+1):
        processUrl = "/segments/" + str(int(idSegment)) + "/outliers/generate/fold/" + str(fold)
        processesUrl.append(processUrl)

    return {
        'status': 'success',
        'data' : processesUrl
    }, status.HTTP_200_OK

@app_gen.route("/segments/<int:idSegment>/outliers/generate/fold/<int:fold>", methods=['GET'])
@app_gen.route("/segments/<int:idSegment>/outliers/generate/drug/<int:idDrug>", methods=['GET'])
@jwt_required
def generateOutliers(idSegment,fold=None,idDrug=None,clean=None):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    conn = db.engine.raw_connection()
    cursor = conn.cursor()

    query = "SELECT fkmedicamento as medication, doseconv as dose, frequenciadia as frequency, contagem as count \
          FROM " + user.schema + ".outlier \
          WHERE idsegmento = " + str(int(idSegment))

    if fold != None:
        query += " AND fkmedicamento IN (\
                  SELECT fkmedicamento FROM " + user.schema + ".outlier\
                  WHERE idsegmento = " + str(int(idSegment))+ "\
                  GROUP BY fkmedicamento\
                  ORDER BY fkmedicamento ASC\
                  LIMIT " + str(fold_size) + " OFFSET " + str((fold-1)*fold_size) + ")"

    if idDrug != None:
        query += " AND fkmedicamento = " + str(int(idDrug))

        if clean != None:
            queryUpdate = "UPDATE " + user.schema + ".presmed SET idoutlier = NULL WHERE fkmedicamento = " + str(int(idDrug)) + " AND idsegmento = " + str(int(idSegment)) + ";"
            result = db.engine.execute(queryUpdate)
            print('RowCount Update Drug', result.rowcount)

            queryDelete = "DELETE FROM " + user.schema + ".outlier WHERE fkmedicamento = " + str(int(idDrug)) + " AND idsegmento = " + str(int(idSegment)) + ";"
            result = db.engine.execute(queryDelete)
            print('RowCount Delete Drug', result.rowcount)

        queryInsert = "INSERT INTO " + user.schema + ".outlier (idsegmento, fkmedicamento, doseconv, frequenciadia, contagem, escore)\
                SELECT idsegmento, fkmedicamento, ROUND(doseconv::numeric,2) as doseconv, frequenciadia, SUM(contagem), NULL\
                FROM " + user.schema + ".prescricaoagg\
                WHERE idsegmento = " + str(int(idSegment)) + "\
                AND fkmedicamento = " + str(int(idDrug)) + " and frequenciadia is not null and doseconv is not null\
                GROUP BY idsegmento, fkmedicamento, ROUND(doseconv::numeric,2), frequenciadia\
                ON CONFLICT DO nothing;"

        result = db.engine.execute(queryInsert)
        print('RowCount Insert Drug', result.rowcount)

        if clean != None and clean == 0: return { 'status': 'success' }, status.HTTP_200_OK

    print(query)

    outputquery = "COPY ({0}) TO STDOUT WITH CSV HEADER".format(query)

    csv_buffer = io.StringIO()
    cursor.copy_expert(outputquery, csv_buffer)
    csv_buffer.seek(0)

    manager = Manager()
    drugs = pd.read_csv(csv_buffer)
    poolDict = manager.dict()

    processes = []
    for idDrug in drugs['medication'].unique():
        drugsItem = drugs[drugs['medication']==idDrug]
        process = Process(target=compute_outlier, args=(idDrug,drugsItem,poolDict,fold,))
        processes.append(process)

    for process in processes:
        process.start()

    for process in processes:
        process.join()

    idDrugs = drugs['medication'].unique().astype(float)
    outliers = Outlier.query\
               .filter(Outlier.idSegment == idSegment)\
               .filter(Outlier.idDrug.in_(idDrugs))\
               .all()

    new_os = pd.DataFrame()
    print('Appending Schema:', user.schema, 'Segment:', idSegment, 'Fold:', fold, 'Drug', idDrug)
    for drug in poolDict:
        new_os = new_os.append(poolDict[drug])

    print('Updating Schema:', user.schema, 'Segment:', idSegment, 'Fold:', fold, 'Drug', idDrug)
    for o in outliers:
        no = new_os[(new_os['medication']==o.idDrug) & 
                    (new_os['dose']==o.dose) &
                    (new_os['frequency']==o.frequency)]
        if len(no) > 0:
            o.score = no['score'].values[0]
            o.countNum = int(no['count'].values[0])

    print('Commiting Schema:', user.schema, 'Segment:', idSegment, 'Fold:', fold)
    db.session.commit()

    return {
        'status': 'success'
    }, status.HTTP_200_OK

@app_gen.route("/segments/<int:idSegment>/outliers/generate/drug/<int:idDrug>/clean/<int:clean>", methods=['POST'])
@jwt_required
def outlierWizard(idSegment, idDrug, clean):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    data = request.get_json()

    division = data.get('division', None)
    idMeasureUnit = data.get('idMeasureUnit', None)
    useWeight = data.get('useWeight', False)
    measureUnitList = data.get('measureUnitList')

    if measureUnitList:
        if idMeasureUnit is None or len(idMeasureUnit) == 0:
            idMeasureUnit = measureUnitList[0]['idMeasureUnit']

        for m in measureUnitList:
            setDrugUnit(idDrug, m['idMeasureUnit'], idSegment, m['fator'])

    drugAttr = DrugAttributes.query.get((idDrug,idSegment))

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
    drugAttr.user  = user.id

    if newDrugAttr: db.session.add(drugAttr)

    db.session.commit()

    generateOutliers(idSegment, None, idDrug, clean)

    return {
        'status': 'success'
    }, status.HTTP_200_OK

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

    if new: db.session.add(u)