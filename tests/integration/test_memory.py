from datetime import datetime

from tests.conftest import session, session_commit

from models.appendix import Memory


def _add_memory(mem_kind, mem_value):
    """Add a memory record and return its key"""
    mem = Memory()
    mem.kind = mem_kind
    mem.value = mem_value
    mem.update = datetime.today()
    mem.user = 0
    session.add(mem)
    session_commit()
    return mem.key


def _delete_memory(key):
    memory = session.query(Memory).get(key)
    if memory:
        session.delete(memory)
        session_commit()


def test_get_non_existing_memory(client, viewer_headers):
    """Test get /memory/ - check status_code 200 and empty array from API"""
    response = client.get("/memory/non-existing-memory", headers=viewer_headers)

    assert response.status_code == 200
    assert response.get_json()["data"] == []


def test_get_existing_memory(client, viewer_headers):
    """Test get /memory/string:kind - check status_code 200 and data array from API"""
    memory_kind_test = "existing-memory"
    memory_value_test = 19

    id_memory = _add_memory(memory_kind_test, memory_value_test)

    response = client.get("/memory/" + memory_kind_test, headers=viewer_headers)
    data = response.get_json()["data"]

    assert response.status_code == 200
    assert data[0]["value"] == memory_value_test
    assert data[0]["key"] == id_memory

    _delete_memory(id_memory)


def test_put_new_memory(client, analyst_headers):
    """Test put /memory/ - check status_code 200 and data from database"""
    data = {"type": "new-memory", "value": "7"}
    response = client.put("memory/", json=data, headers=analyst_headers)
    id_memory = response.get_json()["data"]
    mem = session.query(Memory).get(id_memory)

    assert response.status_code == 200
    assert id_memory == mem.key
    assert data["type"] == mem.kind
    assert data["value"] == mem.value

    _delete_memory(id_memory)


def test_update_memory(client, analyst_headers):
    """Test put /memory/key - check status_code 200 and updated data in database"""
    id_memory = _add_memory("update-memory", 18)

    data = {"type": "updated-memory", "value": "7"}
    response = client.put("memory/" + str(id_memory), json=data, headers=analyst_headers)
    mem = session.query(Memory).get(id_memory)

    assert response.status_code == 200
    assert id_memory == response.get_json()["data"]
    assert data["type"] == mem.kind
    assert data["value"] == mem.value

    _delete_memory(id_memory)


def test_update_non_existing_memory(client, analyst_headers):
    """Test put /memory/900 - check status_code 400 when memory does not exist"""
    _delete_memory(900)

    data = {"type": "updated-memory", "value": "7"}
    response = client.put("memory/900", json=data, headers=analyst_headers)

    assert response.status_code == 400
