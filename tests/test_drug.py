import json

from conftest import get_access, make_headers, session, session_commit
from models.main import Drug, Outlier, Substance
from security.role import Role


def test_get_drugs(client):
    """Teste get /drugs/ - Valida status_code 200"""
    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.get("/drugs", headers=make_headers(access_token))
    data = json.loads(response.data)
    drugsNum = session.query(Drug).count()

    assert response.status_code == 200
    assert len(data["data"]) == drugsNum


def test_get_drugs_by_idSegmento(client):
    """Teste get /drugs/idSegment - Valida status_code 200"""
    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    id = "1"
    response = client.get("/drugs/" + id, headers=make_headers(access_token))
    data = json.loads(response.data)

    segDrugs = (
        session.query(Outlier.idDrug.label("idDrug"))
        .filter(Outlier.idSegment == id)
        .group_by(Outlier.idDrug)
        .subquery()
    )
    drugs = session.query(Drug).filter(Drug.id.in_(segDrugs))
    drugsNum = drugs.count()

    assert response.status_code == 200
    assert len(data["data"]) == drugsNum


def test_get_drugs_by_idSegment_and_qParam(client):
    """Teste get /drugs/idSegment - Valida status_code 200"""
    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    id = "1"

    response = client.get("/drugs/" + id + "?q=a", headers=make_headers(access_token))
    data = json.loads(response.data)

    segDrugs = (
        session.query(Outlier.idDrug.label("idDrug"))
        .filter(Outlier.idSegment == id)
        .group_by(Outlier.idDrug)
        .subquery()
    )

    drugsNum = (
        session.query(Drug)
        .filter(Drug.name.ilike("%a%"))
        .filter(Drug.id.in_(segDrugs))
        .count()
    )

    assert response.status_code == 200
    assert len(data["data"]) == drugsNum


def test_get_drugs_by_non_existing_idSegment(client):
    """Teste get /drugs/idSegment - Valida status_code 200"""
    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    id = "7"

    response = client.get("/drugs/" + id, headers=make_headers(access_token))
    data = json.loads(response.data)

    assert response.status_code == 200
    assert len(data["data"]) == 0


def test_get_drugs_units_by_id(client):
    """Teste get /drugs/id/units - Valida status_code 200"""
    # in this test instead of checking units in database, checking if it returns properties correctly

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    id = "2"

    response = client.get("/drugs/" + id + "/units", headers=make_headers(access_token))
    data = json.loads(response.data)
    # TODO: Add consulta ao banco de dados e comparar retorno (retornando status 200 porém data = [])

    assert response.status_code == 200
    assert "idMeasureUnit" in data["data"][0]
    assert "description" in data["data"][0]
    assert "drugName" in data["data"][0]
    assert "fator" in data["data"][0]
    assert "contagem" in data["data"][0]

    # test the record properties in all other tests as well


def add_substance(sub_id, sub_name):
    """Add a substance"""
    sub = Substance()

    sub.id = sub_id
    sub.name = sub_name
    session.add(sub)
    session_commit()


def test_get_substance(client):
    """Teste get /substance - Valida status_code 200"""
    # add substance since there's no in database. add before the response

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    allSubstances = session.query(Substance).delete()
    session.commit()

    add_substance(1, "substance1")
    add_substance(2, "substance2")

    response = client.get("/substance", headers=make_headers(access_token))
    data = json.loads(response.data)
    # TODO: Add consulta ao banco de dados e comparar retorno (retornando status 200 porém data = [])

    assert response.status_code == 200
    assert len(data["data"]) == 2

    # structure check
    assert "sctid" in data["data"][0]
    assert "name" in data["data"][0]


def test_get_outliers_by_segment_and_drug(client):
    """Teste get /outliers/idSegment/idDrug - Valida status_code 200"""

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    testIdSegment = 1
    testIdDrug = 5

    outlierNum = (
        session.query(Outlier)
        .filter_by(idSegment=testIdSegment, idDrug=testIdDrug)
        .count()
    )

    url = "outliers/{0}/{1}".format(testIdSegment, testIdDrug)
    response = client.get(url, headers=make_headers(access_token))
    data = json.loads(response.data)
    # TODO: Add consulta ao banco de dados e comparar retorno (necessário melhor compreensão dos dados retornados)

    assert response.status_code == 200
    assert len(data["data"]["outliers"]) == outlierNum

    # structure check
    assert "antimicro" in data["data"]
    assert "mav" in data["data"]
    assert "controlled" in data["data"]
