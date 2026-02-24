from tests.conftest import session

from models.prescription import Patient

ADMISSION = "5"


def test_post_patient_permission(client, viewer_headers):
    """Teste post /patient/admission - Deve retornar erro [401 UNAUTHORIZED] devido ao usuário utilizado"""
    response = client.post(
        "patient/" + ADMISSION, json={"height": "15.0"}, headers=viewer_headers
    )

    assert response.status_code == 401


def test_post_patient_permission_support(client, viewer_headers):
    """Teste post /patient/admission - Não deve atualizar informacao"""
    response = client.post(
        "patient/" + ADMISSION, json={"height": "18.0"}, headers=viewer_headers
    )

    assert response.status_code == 401


def test_post_patient(client, analyst_headers):
    """Teste post /patient/admission - Compara dados enviados com dados salvos no banco e valida status_code 200"""
    data = {"height": "15.0"}
    response = client.post("patient/" + ADMISSION, json=data, headers=analyst_headers)
    response_data = response.get_json()["data"]
    patient = session.query(Patient).get(ADMISSION)

    assert response.status_code == 200
    assert data["height"] == str(patient.height)
    assert ADMISSION == str(response_data.get("admissionNumber", None))


def test_get_notes_by_idAdmission(client, analyst_headers):
    """Teste get /notes/idAdmission - Valida status_code 200"""
    response = client.get(f"/notes/{ADMISSION}/v2", headers=analyst_headers)

    assert response.status_code == 200


def test_get_exams_by_idAdmission(client, analyst_headers):
    """Teste get /exams/idAdmission - Valida status_code 200"""
    response = client.get("/exams/" + ADMISSION, headers=analyst_headers)

    assert response.status_code == 200
