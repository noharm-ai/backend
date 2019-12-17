import gzip, requests
from flask_api import status
from flask import Blueprint, request
from multiprocessing import Process
from models import db
from flask_jwt_extended import (jwt_required)
from config import Config

app_gen = Blueprint('app_gen',__name__)

def compute_outlier(val,idSegment,schema):
    conn = db.engine.raw_connection()
    cursor = conn.cursor()

    query = "SELECT fkmedicamento as medication, dose, frequenciadia as frequency, contagem as count \
          FROM " + schema + ".prescricaoagg \
          WHERE idsegmento = " + str(idSegment) + " AND fkmedicamento = "

    outputquery = "COPY ({0}) TO STDOUT WITH CSV HEADER".format(query + val)

    with gzip.open('medication' + val + '.csv.gz', 'w') as f:
        cursor.copy_expert(outputquery, f)

    url = Config.DDC_API_URL + 'score'
    files = {'file': open('medication' + val + '.csv.gz', 'rb')}
    data = {'userid':'hospital'}

    r = requests.post(url, files=files, data=data)

    with open('parallel' + val + '.csv.gz', "wb") as file:
        file.write(r.content)
        file.close()

@app_gen.route("/segments/<int:idSegment>/outliers/generate", methods=['GET'])
@jwt_required
def generateOutliers(idSegment):
    user = User.find(get_jwt_identity())

    processes = []
    for i in range(1,15):
        value = str(i)
        process = Process(target=compute_outlier, args=(value,idSegment,user.schema,))
        processes.append(process)

    for process in processes:
        process.start()

    for process in processes:
        process.join()

    return {
        'status': 'success'
    }, status.HTTP_200_OK