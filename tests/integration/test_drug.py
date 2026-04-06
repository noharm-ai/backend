from models.main import Drug, Outlier, Substance
from tests.conftest import session, session_commit


def test_get_drugs(client, analyst_headers):
    """Teste get /drugs/ - Valida status_code 200"""
    response = client.get("/drugs", headers=analyst_headers)
    drugs_num = session.query(Drug).count()

    assert response.status_code == 200
    assert len(response.get_json()["data"]) == drugs_num


def test_get_drugs_by_idSegmento(client, analyst_headers):
    """Teste get /drugs/idSegment - Valida status_code 200"""
    id = "1"
    response = client.get("/drugs/" + id, headers=analyst_headers)

    seg_drugs = (
        session.query(Outlier.idDrug.label("idDrug"))
        .filter(Outlier.idSegment == id)
        .group_by(Outlier.idDrug)
        .scalar_subquery()
    )
    drugs_num = session.query(Drug).filter(Drug.id.in_(seg_drugs)).count()

    assert response.status_code == 200
    assert len(response.get_json()["data"]) == drugs_num


def test_get_drugs_by_idSegment_and_qParam(client, analyst_headers):
    """Teste get /drugs/idSegment?q=a - Valida status_code 200"""
    id = "1"
    response = client.get("/drugs/" + id + "?q=a", headers=analyst_headers)

    seg_drugs = (
        session.query(Outlier.idDrug.label("idDrug"))
        .filter(Outlier.idSegment == id)
        .group_by(Outlier.idDrug)
        .scalar_subquery()
    )
    drugs_num = (
        session.query(Drug)
        .filter(Drug.name.ilike("%a%"))
        .filter(Drug.id.in_(seg_drugs))
        .count()
    )

    assert response.status_code == 200
    assert len(response.get_json()["data"]) == drugs_num


def test_get_drugs_by_non_existing_idSegment(client, analyst_headers):
    """Teste get /drugs/idSegment - Valida retorno vazio para segmento inexistente"""
    response = client.get("/drugs/7", headers=analyst_headers)

    assert response.status_code == 200
    assert len(response.get_json()["data"]) == 0


def test_get_drugs_units_by_id(client, analyst_headers):
    """Teste get /drugs/id/units - Valida status_code 200 e estrutura da resposta"""
    response = client.get("/drugs/2/units", headers=analyst_headers)
    data = response.get_json()["data"]

    assert response.status_code == 200
    assert "idMeasureUnit" in data[0]
    assert "description" in data[0]
    assert "drugName" in data[0]
    assert "fator" in data[0]
    assert "contagem" in data[0]


def _add_substance(sub_id, sub_name):
    """Add a substance for testing"""
    sub = Substance()
    sub.id = sub_id
    sub.name = sub_name
    session.add(sub)
    session_commit()


def test_get_substance(client, analyst_headers):
    """Teste get /substance - Valida status_code 200"""
    # Only delete test-created substances (IDs >= 10000), preserve seed data
    session.query(Substance).filter(Substance.id >= 10000).delete()
    session.commit()

    _add_substance(10001, "substance1")
    _add_substance(10002, "substance2")

    response = client.get("/substance", headers=analyst_headers)
    data = response.get_json()["data"]

    assert response.status_code == 200

    # structure check
    assert "sctid" in data[0]
    assert "name" in data[0]

    # verify our 2 test substances are present in the response
    response_ids = {d["sctid"] for d in data}
    assert "10001" in response_ids and "10002" in response_ids
