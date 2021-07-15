from flask.json import jsonify
from conftest import *
from models.appendix import Department
from models.segment import Segment
# from models.prescription import Prescription

# def pres_getall():
#   pres = Prescription()
#   pres.id = 1
#   pres.idHospital = 1
#   pres.name = 'pres'
#   return [pres, pres]

@app.route('/authenticate')
def test_get_prescriptions(client):
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
    print(data_response['access_token'])

    response = client.get('/prescriptions', headers=make_headers(data_response['access_token']))
    #data = json.loads(response.data)
    assert response.status_code == 200
    # assert data['status'] == 'success'
    # assert data['data'][0]['description'] == 'descript'
    #assert len(data['data']) == 3
