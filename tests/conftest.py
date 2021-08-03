import pytest, json
from mobile import app
from models.main import User
from unittest.mock import patch
from flask_jwt_extended import (create_access_token)

import psycopg2

with app.test_request_context():
	access_token = create_access_token('1')

def make_headers(jwt):
    return {'Authorization': 'Bearer {}'.format(jwt)}

def user_find(id):
	user = User()
	user.schema = "demo"
	return user

def setSchema(schema):
	return schema

@pytest.fixture
def client():
    client = app.test_client()
    yield client


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