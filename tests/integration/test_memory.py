from datetime import datetime

from sqlalchemy import text

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
    memory = session.get(Memory, key)
    if memory:
        session.delete(memory)
        session_commit()


def _delete_memory_by_kind(kind):
    session.execute(text(f"DELETE FROM demo.memoria WHERE tipo = :kind"), {"kind": kind})
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
    mem = session.get(Memory, id_memory)

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
    mem = session.get(Memory, id_memory)

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


# --- GET /memory (get_editable_memories) ---


def test_get_editable_memories_empty(client, viewer_headers):
    """Test get /memory - returns empty list when no editable (tpl-care-plan) records exist"""
    _delete_memory_by_kind("tpl-care-plan")

    response = client.get("/memory", headers=viewer_headers)

    assert response.status_code == 200
    assert response.get_json()["data"] == []


def test_get_editable_memories(client, viewer_headers):
    """Test get /memory - returns editable records with all required fields"""
    _delete_memory_by_kind("tpl-care-plan")
    id_memory = _add_memory("tpl-care-plan", {"foo": "bar"})

    response = client.get("/memory", headers=viewer_headers)
    data = response.get_json()["data"]

    assert response.status_code == 200
    assert len(data) == 1
    record = data[0]
    assert record["key"] == id_memory
    assert record["kind"] == "tpl-care-plan"
    assert record["value"] == {"foo": "bar"}
    assert "updatedAt" in record

    _delete_memory(id_memory)


# --- GET /memory/id/<id> (get_memory_by_id) ---


def test_get_memory_by_id_not_found(client, viewer_headers):
    """Test get /memory/id/999999999 - returns 400 when ID does not exist"""
    response = client.get("/memory/id/999999999", headers=viewer_headers)

    assert response.status_code == 400


def test_get_memory_by_id_non_editable_kind(client, viewer_headers):
    """Test get /memory/id/<id> - returns 400 when kind is not in EDITABLE_KINDS"""
    id_memory = _add_memory("non-editable-kind", 42)

    response = client.get(f"/memory/id/{id_memory}", headers=viewer_headers)

    assert response.status_code == 400

    _delete_memory(id_memory)


def test_get_memory_by_id_editable_kind(client, viewer_headers):
    """Test get /memory/id/<id> - returns 200 with all fields for an editable kind"""
    id_memory = _add_memory("tpl-care-plan", {"x": 1})

    response = client.get(f"/memory/id/{id_memory}", headers=viewer_headers)
    data = response.get_json()["data"]

    assert response.status_code == 200
    assert data["key"] == id_memory
    assert data["kind"] == "tpl-care-plan"
    assert data["value"] == {"x": 1}
    assert "updatedAt" in data

    _delete_memory(id_memory)


# --- GET /memory/<kind> additional cases ---


def test_get_admin_restricted_memory(client, viewer_headers):
    """Test get /memory/features - returns 400 for admin-restricted kinds"""
    response = client.get("/memory/features", headers=viewer_headers)

    assert response.status_code == 400


def test_get_custom_forms_memory(client, viewer_headers):
    """Test get /memory/custom-forms - returns 200 (admin-restricted exception)"""
    response = client.get("/memory/custom-forms", headers=viewer_headers)

    assert response.status_code == 200


# --- PUT /memory/ permission and validation ---


def test_put_memory_requires_write_permission(client, viewer_headers):
    """Test put /memory/ - returns 401 when user lacks WRITE_BASIC_FEATURES"""
    data = {"type": "some-kind", "value": "x"}
    response = client.put("/memory/", json=data, headers=viewer_headers)

    assert response.status_code == 401


def test_put_admin_kind_rejected(client, analyst_headers):
    """Test put /memory/ - returns 401 when trying to save an admin-restricted kind"""
    data = {"type": "features", "value": {"flag": True}}
    response = client.put("/memory/", json=data, headers=analyst_headers)

    assert response.status_code == 401


def test_put_duplicate_editable_kind_rejected(client, analyst_headers):
    """Test put /memory/ - returns 400 when creating a duplicate EDITABLE_KIND record"""
    _delete_memory_by_kind("tpl-care-plan")
    id_memory = _add_memory("tpl-care-plan", 1)

    data = {"type": "tpl-care-plan", "value": 2}
    response = client.put("/memory/", json=data, headers=analyst_headers)

    assert response.status_code == 400

    _delete_memory(id_memory)


# --- PUT /memory/custom-forms ---


def test_put_custom_form_requires_permission(client, analyst_headers):
    """Test put /memory/custom-forms - returns 401 when user lacks WRITE_CUSTOM_FORMS"""
    data = {"value": {"field": "x"}}
    response = client.put("/memory/custom-forms", json=data, headers=analyst_headers)

    assert response.status_code == 401


def test_put_custom_form_create(client, admin_headers):
    """Test put /memory/custom-forms - creates a new custom-forms record"""
    _delete_memory_by_kind("custom-forms")

    data = {"value": {"field": "x"}}
    response = client.put("/memory/custom-forms", json=data, headers=admin_headers)

    assert response.status_code == 200

    id_memory = response.get_json()["data"]
    session.expire_all()
    mem = session.get(Memory, id_memory)

    assert mem is not None
    assert mem.kind == "custom-forms"
    assert mem.value == {"field": "x"}

    _delete_memory(id_memory)


def test_put_custom_form_update(client, admin_headers):
    """Test put /memory/custom-forms/<id> - updates an existing custom-forms record"""
    id_memory = _add_memory("custom-forms", {"old": True})

    data = {"value": {"new": True}}
    response = client.put(f"/memory/custom-forms/{id_memory}", json=data, headers=admin_headers)

    assert response.status_code == 200

    session.expire_all()
    mem = session.get(Memory, id_memory)

    assert mem.value == {"new": True}

    _delete_memory(id_memory)


# --- PUT /memory/unique/<kind> ---


def test_put_unique_memory_requires_write_permission(client, viewer_headers):
    """Test put /memory/unique/<kind> - returns 401 when user lacks WRITE_BASIC_FEATURES"""
    data = {"value": 99}
    response = client.put("/memory/unique/unique-test-kind", json=data, headers=viewer_headers)

    assert response.status_code == 401


def test_put_unique_memory_admin_kind_rejected(client, analyst_headers):
    """Test put /memory/unique/features - returns 401 for admin-restricted kinds"""
    data = {"value": {"flag": True}}
    response = client.put("/memory/unique/features", json=data, headers=analyst_headers)

    assert response.status_code == 401


def test_put_unique_memory_create(client, analyst_headers):
    """Test put /memory/unique/<kind> - creates a record when none exists"""
    _delete_memory_by_kind("unique-test-kind")

    data = {"value": 99}
    response = client.put("/memory/unique/unique-test-kind", json=data, headers=analyst_headers)

    assert response.status_code == 200

    id_memory = response.get_json()["data"]
    session.expire_all()
    mem = session.get(Memory, id_memory)

    assert mem is not None
    assert mem.kind == "unique-test-kind"
    assert mem.value == 99

    count = session.query(Memory).filter(Memory.kind == "unique-test-kind").count()
    assert count == 1

    _delete_memory(id_memory)


def test_put_unique_memory_update(client, analyst_headers):
    """Test put /memory/unique/<kind> - updates existing record without creating a duplicate"""
    _delete_memory_by_kind("unique-test-kind2")
    id_memory = _add_memory("unique-test-kind2", "old")

    data = {"value": "new"}
    response = client.put("/memory/unique/unique-test-kind2", json=data, headers=analyst_headers)

    assert response.status_code == 200

    session.expire_all()
    count = session.query(Memory).filter(Memory.kind == "unique-test-kind2").count()
    assert count == 1

    mem = session.get(Memory, id_memory)
    assert mem.value == "new"

    _delete_memory(id_memory)
