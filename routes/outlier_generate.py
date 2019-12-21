import gzip, requests, io
from flask_api import status
from flask import Blueprint, request
from multiprocessing import Process, Manager
from models import db, User, setSchema, Outlier
from flask_jwt_extended import (jwt_required, get_jwt_identity)
from config import Config
import pandas as pd

app_gen = Blueprint('app_gen',__name__)

def compute_outlier(idDrug,drugsItem,poolDict):
    print('Starting...', idDrug)
    str_buffer = io.StringIO()
    drugsItem.to_csv(str_buffer, index=None)

    gz_buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=gz_buffer, mode='wb') as zipped:
        zipped.write(bytes(str_buffer.getvalue(), 'utf-8'))

    url = Config.DDC_API_URL + '/score'
    files = {'file': gz_buffer.getvalue()}
    data = {'userid':'1'}

    r = requests.post(url, files=files, data=data)

    ungz_buffer = io.BytesIO()
    ungz_buffer.write(r.content)
    ungz_buffer.seek(0)

    poolDict[idDrug] = pd.read_csv(ungz_buffer, compression='gzip')
    print('End...', idDrug)


@app_gen.route("/segments/<int:idSegment>/outliers/generate", methods=['GET'])
@jwt_required
def generateOutliers(idSegment):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    conn = db.engine.raw_connection()
    cursor = conn.cursor()

    print('Starting...', user.schema, idSegment)

    query = "INSERT INTO " + user.schema + ".outlier (idsegmento, fkmedicamento, dose, frequenciadia, contagem) \
            SELECT idsegmento, fkmedicamento, dose, frequenciadia, SUM(contagem) \
            FROM demo.prescricaoagg \
            WHERE idsegmento = " + str(int(idSegment)) + " \
            GROUP BY idsegmento, fkmedicamento, dose, frequenciadia \
            ON CONFLICT DO NOTHING"

    cursor.execute(query)

    query = "SELECT fkmedicamento as medication, dose, frequenciadia as frequency, SUM(contagem) as count \
          FROM " + user.schema + ".prescricaoagg \
          WHERE idsegmento = " + str(int(idSegment)) + " \
          GROUP BY fkmedicamento, dose, frequenciadia"

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
        process = Process(target=compute_outlier, args=(idDrug,drugsItem,poolDict,))
        processes.append(process)

    for process in processes:
        process.start()

    for process in processes:
        process.join()

    outliers = Outlier.query.filter(Outlier.idSegment == idSegment).all()

    print('Appending...', user.schema, idSegment)
    new_os = pd.DataFrame()
    for drug in poolDict:
        new_os = new_os.append(poolDict[drug])

    print('Updating...', user.schema, idSegment)
    for o in outliers:
        no = new_os[(new_os['medication']==o.idDrug) & 
                    (new_os['dose']==o.dose) &
                    (new_os['frequency']==o.frequency)]
        if len(no) > 0:
            o.score = no['score'].values[0]
            o.countNum = int(no['count'].values[0])

    print('Commiting...', user.schema, idSegment)
    db.session.commit()

    return {
        'status': 'success'
    }, status.HTTP_200_OK