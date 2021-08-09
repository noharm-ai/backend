from conftest import *

@pytest.mark.skip(reason="WIP")
def test_get_drugs(client):

    access_token = get_access(client)

    response = client.get('/drugs', headers=make_headers(access_token))
    data = json.loads(response.data)

    assert response.status_code == 200

@pytest.mark.skip(reason="WIP")
def test_get_drugs_by_id(client):

    access_token = get_access(client)

    id = '0'

    response = client.get('/drugs/' + id, headers=make_headers(access_token))
    data = json.loads(response.data)

    assert response.status_code == 200
