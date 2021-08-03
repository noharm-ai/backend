from conftest import *

def test_get_drugs(client):

    access_token = get_access(client)

    response = client.get('/drugs', headers=make_headers(access_token))
    data = json.loads(response.data)

    breakpoint()

    assert response.status_code == 200