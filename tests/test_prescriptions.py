from flask.json import jsonify
from conftest import *
from models.appendix import Department
from models.segment import Segment
# from models.prescription import Prescription

from pytest_postgresql import factories
import psycopg2

# def pres_getall():
#   pres = Prescription()
#   pres.id = 1
#   pres.idHospital = 1
#   pres.name = 'pres'
#   return [pres, pres]


def get_db_conn():
    # configurações
    host = 'localhost'
    dbname = 'noharm'
    user = 'postgres'
    password = 'postgres'    
    sslmode = 'require'
    port = '5432'

    # string conexão
    conn_string = 'host={0} user={1} dbname={2} password={3} port={4}'.format(host, user, dbname, password, port)

    conn = psycopg2.connect(conn_string)
    return conn

def get_access(client):
    mimetype = 'application/json'
    headers = {
        'Content-Type': mimetype,
        'Accept': mimetype
    }
    data = {
        "email": "demo",
        "password": "demo"
    }
    url = '/authenticate'

    response = client.post(url, data=json.dumps(data), headers=headers)
    my_json = response.data.decode('utf8').replace("'", '"')
    data_response = json.loads(my_json)
    access_token = data_response['access_token']
    return access_token

def test_get_prescriptions(client):

    access_token = get_access(client)

    response = client.get('/prescriptions', headers=make_headers(access_token))
    #data = json.loads(response.data)
    assert response.status_code == 200
    # assert data['status'] == 'success'
    # assert data['data'][0]['description'] == 'descript'
    #assert len(data['data']) == 3

def test_get_prescriptions_by_id(client):

    access_token = get_access(client)

    response = client.get('/prescriptions/20', headers=make_headers(access_token))
    data = json.loads(response.data)

    conn = get_db_conn()
    cursor = conn.cursor()
    # buscar fkprescricao, prescription, solution, interventions, exams, alertExams, status
    cursor.execute("select * from demo.prescricao where fkprescricao = 20")
    result = cursor.fetchall()
    result_columns = cursor.description
    cursor.close()
    conn.close()

    assert response.status_code == 200
    # assert data['data']['idPrescription'] == '20'
    # assert data['data']['prescription']
    # assert data['data']['solution']
    # assert data['data']['interventions']
    # assert data['data']['exams']
    # assert data['data']['alertExams']
    # assert data['data']['status']

def test_get_drugs(client):

    access_token = get_access(client)

    response = client.get('/drugs', headers=make_headers(access_token))
    data = json.loads(response.data)

    breakpoint()

    assert response.status_code == 200