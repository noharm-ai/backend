from conftest import *
from models.appendix import Memory
from datetime import datetime

def test_get_non_existing_memory(client):
    """Test get /memory/ - check status_code 200 and empty array"""
    access_token = get_access(client) #client login > receive token(temporaly key for one day)

    response = client.get('/memory/non-existing-memory', headers=make_headers(access_token)) # all the commutication client and server will be json
    object = json.loads(response.data) # json.loads >> going to transform json string into python structure
    # TODO: Add consulta ao banco de dados e comparar retorno (retornando status 200 porém data = [])

    assert response.status_code == 200
    # assert object['data'][0]['value'] == 18
    assert object['data'] == [] 

    # assert status code auth
    # assert memory key
    # assert memory value

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
    session.delete(memory)
    session_commit()

def test_get_existing_memory(client):
    """Test get /memory/string:kind - check status_code 200 and data array"""

    memory_kind_test = 'memory-new'
    memory_value_test = 18

    keyMemory = add_memory(memory_kind_test, memory_value_test)

    access_token = get_access(client) #client login > receive token(temporaly key for one day)

    response = client.get('/memory/' + memory_kind_test, headers=make_headers(access_token)) # all the commutication client and server will be json
    object = json.loads(response.data) # json.loads >> going to transform json string into python structure
    # TODO: Add consulta ao banco de dados e comparar retorno (retornando status 200 porém data = [])

    assert response.status_code == 200
    assert object['data'][0]['value'] == memory_value_test

    delete_memory(keyMemory)

def test_put_new_memory(client):
    """Teste put /intervention - Deve retornar erro [401 UNAUTHORIZED] devido ao usuário utilizado"""

    access_token = get_access(client)

    idPrescriptionDrug = '20'
    data = {
        "status": "s",
        "admissionNumber": "5"  
    }
    url = 'intervention/' + idPrescriptionDrug
    
    response = client.put(url, data=json.dumps(data), headers=make_headers(access_token))
    assert response.status_code == 401

# def test_update_memory(client):

# def test_update_non_existing_memory(client):

# run test-memory : python -m pytest -vs tests/test_memory.py 