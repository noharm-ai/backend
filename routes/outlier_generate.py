import gzip, requests, io
from flask_api import status
from flask import Blueprint, request
from multiprocessing import Process
from models import db, User, setSchema, Outlier
from flask_jwt_extended import (jwt_required, get_jwt_identity)
from config import Config
import pandas as pd

app_gen = Blueprint('app_gen',__name__)

def compute_outlier(idDrug, idSegment, schema):
    conn = db.engine.raw_connection()
    cursor = conn.cursor()
    setSchema(schema)

    query = "INSERT INTO " + schema + ".outlier (idsegmento, fkmedicamento, dose, frequenciadia, contagem) \
            SELECT idsegmento, fkmedicamento, dose, frequenciadia, SUM(contagem) \
            FROM demo.prescricaoagg \
            WHERE idsegmento = " + str(int(idSegment)) + " \
            AND fkmedicamento = " + str(int(idDrug)) + " \
            GROUP BY idsegmento, fkmedicamento, dose, frequenciadia \
            ON CONFLICT DO NOTHING"

    cursor.execute(query)

    query = "SELECT fkmedicamento as medication, dose, frequenciadia as frequency, SUM(contagem) as count \
          FROM " + schema + ".prescricaoagg \
          WHERE idsegmento = " + str(int(idSegment)) + " \
          AND fkmedicamento = " + str(int(idDrug)) + " \
          GROUP BY fkmedicamento, dose, frequenciadia"

    outputquery = "COPY ({0}) TO STDOUT WITH CSV HEADER".format(query)

    gz_buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=gz_buffer, mode='wb') as zipped:
        cursor.copy_expert(outputquery, zipped)

    url = Config.DDC_API_URL + '/score'
    files = {'file': gz_buffer.getvalue()}
    data = {'userid':'1'}

    r = requests.post(url, files=files, data=data)

    ungz_buffer = io.BytesIO()
    ungz_buffer.write(r.content)
    ungz_buffer.seek(0)

    new_os = pd.read_csv(ungz_buffer, compression='gzip')

    outliers = Outlier.query\
        .filter(Outlier.idSegment == idSegment, Outlier.idDrug == idDrug)\
        .all()

    for o in outliers:
        no = new_os[(new_os['frequency']==o.frequency) & (new_os['dose']==o.dose)]
        if len(no) > 0:
            o.score = no['score'].values[0]
            o.countNum = int(no['count'].values[0])

    db.session.commit()

@app_gen.route("/segments/<int:idSegment>/outliers/generate", methods=['GET'])
@jwt_required
def generateOutliers(idSegment):
    user = User.find(get_jwt_identity())
    setSchema(user.schema)

    processes = []
    for i in range(1,15):
        idDrug = str(i)
        process = Process(target=compute_outlier, args=(idDrug,idSegment,user.schema,))
        processes.append(process)

    for process in processes:
        process.start()

    for process in processes:
        process.join()

    return {
        'status': 'success'
    }, status.HTTP_200_OK