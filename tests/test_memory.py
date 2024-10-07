from conftest import *
from models.appendix import Memory
from datetime import datetime
from security.role import Role


def test_get_non_existing_memory(client):
    """Test get /memory/ - check status_code 200 and empty array from API"""
    access_token = get_access(client, roles=[Role.VIEWER.value])

    response = client.get(
        "/memory/non-existing-memory", headers=make_headers(access_token)
    )  # all the commutication client and server will be json
    object = json.loads(
        response.data
    )  # json.loads >> going to transform json string into python structure
    # TODO: Add consulta ao banco de dados e comparar retorno (retornando status 200 porém data = [])

    assert response.status_code == 200
    # assert object['data'][0]['value'] == 18
    assert object["data"] == []  # needs to return empty array of data


def add_memory(mem_kind, mem_value):
    """Add a memory"""
    mem = Memory()

    mem.kind = mem_kind
    mem.value = mem_value
    mem.update = datetime.today()
    mem.user = 0

    session.add(mem)
    session_commit()
    return mem.key


def delete_memory(key):
    memory = session.query(Memory).get(key)
    if memory:
        session.delete(memory)
        session_commit()


def test_get_existing_memory(client):
    """Test get /memory/string:kind - check status_code 200 and data array from API"""

    memory_kind_test = "existing-memory"  # name of the memory
    memory_value_test = 19  # value of the memory

    idMemory = add_memory(memory_kind_test, memory_value_test)

    access_token = get_access(client, roles=[Role.VIEWER.value])

    response = client.get(
        "/memory/" + memory_kind_test, headers=make_headers(access_token)
    )  # API call.  all the commutication client and server will be json
    object = json.loads(
        response.data
    )  # json.loads >> going to transform json string into python structure
    # TODO: Add consulta ao banco de dados e comparar retorno (retornando status 200 porém data = [])

    assert response.status_code == 200
    assert object["data"][0]["value"] == memory_value_test
    assert object["data"][0]["key"] == idMemory
    # OPtional 1. Use faker to populate fake memory values
    # OPtional 2. Loop through the values several time
    # OPtional 3. create multiple memory with same kind/name and assert all of them

    delete_memory(idMemory)


def test_put_new_memory(client):
    """Test put /memory/ - check status_code 200 and data from database"""

    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    data = {"type": "new-memory", "value": "7"}
    url = "memory/"

    response = client.put(
        url, data=json.dumps(data), headers=make_headers(access_token)
    )
    object = json.loads(response.data)
    idMemory = object["data"]
    mem = session.query(Memory).get(idMemory)

    assert response.status_code == 200
    assert idMemory == mem.key
    assert data["type"] == mem.kind
    assert data["value"] == mem.value

    delete_memory(idMemory)


def test_update_memory(client):
    memory_kind_test = "update-memory"
    memory_value_test = 18
    idMemory = add_memory(memory_kind_test, memory_value_test)  # key of memory object
    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    # data to update using API
    data = {"type": "updated-memory", "value": "7"}
    url = "memory/" + str(idMemory)  # idMemory is Id of update-memory object
    response = client.put(
        url, data=json.dumps(data), headers=make_headers(access_token)
    )
    object = json.loads(response.data)
    mem = session.query(Memory).get(
        idMemory
    )  # memory object with updated data from database

    assert response.status_code == 200
    assert idMemory == object["data"]
    assert data["type"] == mem.kind
    assert data["value"] == mem.value

    delete_memory(idMemory)


def test_update_non_existing_memory(client):
    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    delete_memory(900)  # make sure that record doesn't exist
    # data to update using API
    data = {"type": "updated-memory", "value": "7"}
    url = "memory/900"
    response = client.put(
        url, data=json.dumps(data), headers=make_headers(access_token)
    )

    assert response.status_code == 400
