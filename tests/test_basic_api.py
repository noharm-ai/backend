from conftest import *

def getMem(kind, default):
	return default

def test_simple_get(client):
	response = client.get('/version')
	data = json.loads(response.data)

	assert response.status_code == 200

def test_no_auth(client):
	response = client.get('/reports')
	
	assert response.status_code == 401

@patch('models.main.User.find', side_effect=user_find)
@patch('models.appendix.Memory.getMem', side_effect=getMem)
@patch('models.main.dbSession.setSchema', side_effect=setSchema)
def test_reports(user, memory, main, client):
	response = client.get('/reports', headers=make_headers(access_token))
	data = json.loads(response.data)

	assert response.status_code == 200
	assert data['status'] == 'success'
	assert data['reports'] == []

SEGMENT="1"
DRUG="5"
PRESCRIPTION="20"
PRESCRIPTIONDRUG="20"
ADMISSION="5"

def test_getInterventionReasons(client):
	"""Teste get /intervention/reasons - Valida o status_code 200."""

	url = "/intervention/reasons"

	access_token = get_access(client)

	response = client.get(url, headers=make_headers(access_token))
	object=json.loads(response.data)

	print (object)

	assert response.status_code == 200


def test_getIntervention(client):
	"""Teste get /intervention - Valida o status_code 200."""

	url = "/intervention"

	access_token = get_access(client)

	response = client.get(url, headers=make_headers(access_token))
	object=json.loads(response.data)

	print (object)

	assert response.status_code == 200

def test_getSubstance(client):
	"""Teste get /substance - Valida o status_code 200."""

	url = "/substance"

	access_token = get_access(client)

	response = client.get(url, headers=make_headers(access_token))
	object=json.loads(response.data)

	print (object)

	assert response.status_code == 200

def test_getDrugs(client):
	"""Teste get /drugs/idSegment - Valida o status_code 200."""
	
	url = f"/drugs/{SEGMENT}"

	access_token = get_access(client)

	response = client.get(url, headers=make_headers(access_token))
	object=json.loads(response.data)

	print (object)

	assert response.status_code == 200

def test_getPrescriptionsSegment(client):
	"""Teste get /prescriptions?idSegment=idSegment&date=2020-12-31 - Valida o status_code 200."""

	url = f"/prescriptions?idSegment={SEGMENT}&date=2020-12-31"

	access_token = get_access(client)

	response = client.get(url, headers=make_headers(access_token))
	object=json.loads(response.data)

	print (object)

	assert response.status_code == 200

def test_getPrescriptions(client):
	"""Teste get /prescriptions/idPrescription - Valida o status_code 200."""

	url = f"/prescriptions/{PRESCRIPTION}"

	access_token = get_access(client)

	response = client.get(url, headers=make_headers(access_token))
	object=json.loads(response.data)

	print (object)

	assert response.status_code == 200

def test_getPrescriptionsDrug(client):
	"""Teste get /prescriptions/drug/idPrescriptionDrug/period - Valida o status_code 200."""

	url = f"/prescriptions/drug/{PRESCRIPTIONDRUG}/period"

	access_token = get_access(client)

	response = client.get(url, headers=make_headers(access_token))
	object=json.loads(response.data)

	print (object)

	assert response.status_code == 200

def test_getStaticPrescription(client):
	"""Teste get /static/demo/prescription/idPrescription - Valida o status_code 200."""

	url = f"/static/demo/prescription/{PRESCRIPTION}"

	access_token = get_access(client)

	response = client.get(url, headers=make_headers(access_token))
	object=json.loads(response.data)

	print (object)

	assert response.status_code == 200

def test_getExams(client):
	"""Teste get /exams/isAdmission - Valida o status_code 200."""

	url = f"/exams/{ADMISSION}"

	access_token = get_access(client)

	response = client.get(url, headers=make_headers(access_token))
	object=json.loads(response.data)

	print (object)

	assert response.status_code == 200

def test_getSegments(client):
	"""Teste get /segments - Valida o status_code 200."""

	url = "/segments"

	access_token = get_access(client)

	response = client.get(url, headers=make_headers(access_token))
	object=json.loads(response.data)

	print (object)

	assert response.status_code == 200

def test_getSegmentsID(client):
	"""Teste get /segments/idSegment - Valida o status_code 200."""

	url = f"/segments/{SEGMENT}"

	access_token = get_access(client)

	response = client.get(url, headers=make_headers(access_token))
	object=json.loads(response.data)

	print (object)

	assert response.status_code == 200

def test_getDepartments(client):
	"""Teste get /departments - Valida o status_code 200."""

	url = "/departments"

	access_token = get_access(client)

	response = client.get(url, headers=make_headers(access_token))
	object=json.loads(response.data)

	print (object)

	assert response.status_code == 200

def test_getSegmentsExams(client):
	"""Teste get /segments/exams/types - Valida o status_code 200."""

	url = "/segments/exams/types"

	access_token = get_access(client)

	response = client.get(url, headers=make_headers(access_token))
	object=json.loads(response.data)

	print (object)

	assert response.status_code == 200

def test_getNotes(client):
	"""Teste get /notes/idAdmission - Valida o status_code 200."""

	url = f"/notes/{ADMISSION}"

	access_token = get_access(client)

	response = client.get(url, headers=make_headers(access_token))
	object=json.loads(response.data)

	print (object)

	assert response.status_code == 200

def test_getSegmentsDrug(client):
	"""Teste get /segments/idSegment/outliers/generate/drug/idDrug - Valida o status_code 200."""

	url = f"/segments/{SEGMENT}/outliers/generate/drug/{DRUG}"

	access_token = get_access(client)

	response = client.get(url, headers=make_headers(access_token))
	object=json.loads(response.data)

	print (object)

	assert response.status_code == 200

def test_putPrescriprions(client):
	"""Teste put /prescriptions/idPrescription - Assegura que o usuário com role support não tenha autorização para chamar o endpoint."""

	url = f"/prescriptions/{PRESCRIPTION}"

	access_token = get_access(client)
	
	data= {
             "status": "s"
        }

	response = client.put(url, data=json.dumps(data), headers=make_headers(access_token))
	object=json.loads(response.data)

	print (object)

	assert response.status_code == 401

def test_postPatient(client):
	"""Teste post /patient/idAdmission - Assegura que o usuário com role support não tenha autorização para chamar o endpoint."""

	url = f"/patient/{ADMISSION}"

	access_token = get_access(client)
	
	data= {
             "height": 15
        }

	response = client.post(url, data=json.dumps(data), headers=make_headers(access_token))
	object=json.loads(response.data)

	print (object)

	assert response.status_code == 401

def test_putIntervention(client):
	"""Teste put /intervention/idPrescriptionDrug - Assegura que o usuário com role support não tenha autorização para chamar o endpoint."""

	url = f"/intervention/{PRESCRIPTIONDRUG}"

	access_token = get_access(client)
	
	data= {
             "status": "s",
			 "admissionNumber": 5
        }

	response = client.put(url, data=json.dumps(data), headers=make_headers(access_token))
	object=json.loads(response.data)

	print (object)

	assert response.status_code == 401

def test_getPrescriptions404(client):
	"""Teste get /prescriptions/404 - Valida o status_code 400."""

	url = "/prescriptions/404"

	access_token = get_access(client)

	response = client.get(url, headers=make_headers(access_token))
	object=json.loads(response.data)

	print (object)

	assert response.status_code == 400

def test_putDrug(client):
	"""Teste put /drugs/idDrug - Deve retornar o código 200, indicando funcionamento do endpoint."""

	url = f"/drugs/{DRUG}"

	access_token = get_access(client)
	
	data= {
             "idSegment": 1,
			 "mav": True	
        }
	
	response = client.put(url, data=json.dumps(data), headers=make_headers(access_token))
	object=json.loads(response.data)

	print (object)

	assert response.status_code == 200

def test_putPrescription(client):
	"""Teste put /prescriptions/idPrescription - Deve retornar o código 200, indicando funcionamento do endpoint."""

	url = f"/prescriptions/{PRESCRIPTION}"

	access_token = get_access(client, roles=[])
	
	data= {
             "status": "s"
        }
	
	response = client.put(url, data=json.dumps(data), headers=make_headers(access_token))
	object=json.loads(response.data)

	print (object)

	assert response.status_code == 200

def test_postPatient404(client):
	"""Teste post /patient/idAsmission - Deve retornar o código 200, indicando funcionamento do endpoint."""

	url = f"/patient/{ADMISSION}"

	access_token = get_access(client, roles=[])
	
	data= {
             "height": 15	
        }
	
	response = client.post(url, data=json.dumps(data), headers=make_headers(access_token))
	object=json.loads(response.data)

	print (object)

	assert response.status_code == 200

def test_putPrescriptionsDrug(client):
	"""Teste put /prescriptions/drug/idPrescriptiondrug - Deve retornar o código 200, indicando funcionamento do endpoint."""

	url = f"/prescriptions/drug/{PRESCRIPTIONDRUG}"

	access_token = get_access(client, roles=[])
	
	data= {
            "notes": "some notes",
	     	"admissionNumber": 5
        }
	
	response = client.put(url, data=json.dumps(data), headers=make_headers(access_token))
	object=json.loads(response.data)

	print (object)

	assert response.status_code == 200

def test_putInterventionPDrug(client):
	"""Teste put /prescriptions/drug/idPrescriptiondrug - Deve retornar o código 200, indicando funcionamento do endpoint."""

	url = f"/intervention/{PRESCRIPTIONDRUG}"

	access_token = get_access(client, roles=[])
	
	data= {
            "status": "s",
	     	"admissionNumber": 15
        }
	
	response = client.put(url, data=json.dumps(data), headers=make_headers(access_token))
	object=json.loads(response.data)

	print (object)

	assert response.status_code == 200