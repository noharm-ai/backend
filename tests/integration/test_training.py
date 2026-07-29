"""Integration tests for the training feature (list / items / finish flow).

The seed database ships with no training data, so these tests create their own
training module (ids >= 990000, in the shared ``public`` schema) and remove it
afterwards. Completion records are written for the ``demo`` user (id 1), which
is the user behind the ``analyst_headers`` fixture.
"""

import pytest
from sqlalchemy import text

from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit

TRAINING_ID = 990001
INACTIVE_TRAINING_ID = 990002
ITEM_1_ID = 990001
ITEM_2_ID = 990002
INACTIVE_ITEM_ID = 990003
DEMO_USER_ID = 1


def _add_training(training_id, position, active=True):
    """Insert a training module in the public schema (``pagina`` is an array)."""
    session.execute(
        text(
            "INSERT INTO public.treinamento "
            "(idtreinamento, pagina, titulo, resumo, posicao, ativo, obrigatorio, "
            "created_at, created_by) "
            "VALUES (:id, :pagina, :titulo, :resumo, :posicao, :ativo, false, "
            "now(), :created_by)"
        ),
        {
            "id": training_id,
            "pagina": ["page-%d" % training_id],
            "titulo": "Training %d" % training_id,
            "resumo": "Description %d" % training_id,
            "posicao": position,
            "ativo": active,
            "created_by": DEMO_USER_ID,
        },
    )


def _add_item(item_id, training_id, position, active=True):
    """Insert a training item (lesson) in the public schema."""
    session.execute(
        text(
            "INSERT INTO public.treinamento_item "
            "(idtreinamento_item, idtreinamento, titulo, texto, posicao, ativo, "
            "created_at, created_by) "
            "VALUES (:id, :training_id, :titulo, :texto, :posicao, :ativo, "
            "now(), :created_by)"
        ),
        {
            "id": item_id,
            "training_id": training_id,
            "titulo": "Item %d" % item_id,
            "texto": "Text %d" % item_id,
            "posicao": position,
            "ativo": active,
            "created_by": DEMO_USER_ID,
        },
    )


def _clear_user_progress():
    """Remove this user's completion records for the seeded training."""
    session.execute(
        text(
            "DELETE FROM public.treinamento_item_usuario "
            "WHERE idtreinamento_item >= 990000 AND idusuario = :uid"
        ),
        {"uid": DEMO_USER_ID},
    )
    session.execute(
        text(
            "DELETE FROM public.treinamento_usuario "
            "WHERE idtreinamento >= 990000 AND idusuario = :uid"
        ),
        {"uid": DEMO_USER_ID},
    )
    session_commit()


@pytest.fixture(scope="module", autouse=True)
def seed_training():
    """Create a training module with active/inactive rows, tear it down after."""
    _clear_user_progress()
    session.execute(text("DELETE FROM public.treinamento_item WHERE idtreinamento_item >= 990000"))
    session.execute(text("DELETE FROM public.treinamento WHERE idtreinamento >= 990000"))
    session_commit()

    _add_training(TRAINING_ID, position=10, active=True)
    _add_training(INACTIVE_TRAINING_ID, position=11, active=False)
    _add_item(ITEM_1_ID, TRAINING_ID, position=1, active=True)
    _add_item(ITEM_2_ID, TRAINING_ID, position=2, active=True)
    _add_item(INACTIVE_ITEM_ID, TRAINING_ID, position=3, active=False)
    session_commit()

    yield

    _clear_user_progress()
    session.execute(text("DELETE FROM public.treinamento_item WHERE idtreinamento_item >= 990000"))
    session.execute(text("DELETE FROM public.treinamento WHERE idtreinamento >= 990000"))
    session_commit()


@pytest.fixture(autouse=True)
def reset_progress():
    """Each test starts with no completion recorded for the seeded training."""
    _clear_user_progress()
    yield
    _clear_user_progress()


def _find_training(data, training_id):
    """Return the seeded training entry from a /training/list payload."""
    return next((t for t in data if t["id"] == training_id), None)


# --- GET /training/list ---


def test_list_trainings_returns_active_module(client, analyst_headers):
    """GET /training/list returns the active module with its lesson counts."""
    response = client.get("/training/list", headers=analyst_headers)
    data = response.get_json()["data"]

    assert response.status_code == 200

    training = _find_training(data, TRAINING_ID)
    assert training is not None
    assert training["title"] == "Training %d" % TRAINING_ID
    assert training["totalLessons"] == 2
    assert training["totalLessonsFinished"] == 0
    assert training["finished"] is False


def test_list_trainings_excludes_inactive_module(client, analyst_headers):
    """GET /training/list does not include inactive training modules."""
    response = client.get("/training/list", headers=analyst_headers)
    data = response.get_json()["data"]

    assert response.status_code == 200
    assert _find_training(data, INACTIVE_TRAINING_ID) is None


def test_list_trainings_requires_basic_features_permission(client):
    """GET /training/list returns 401 for a role without READ_BASIC_FEATURES."""
    headers = make_headers(
        get_access(client, roles=[Role.SUPPORT_REQUESTER.value])
    )
    response = client.get("/training/list", headers=headers)

    assert response.status_code == 401


# --- GET /training/<id>/items ---


def test_list_training_items_returns_only_active_items_in_order(
    client, analyst_headers
):
    """GET /training/<id>/items returns active items ordered by position."""
    response = client.get(f"/training/{TRAINING_ID}/items", headers=analyst_headers)
    data = response.get_json()["data"]

    assert response.status_code == 200

    ids = [item["id"] for item in data]
    assert ids == [ITEM_1_ID, ITEM_2_ID]
    assert INACTIVE_ITEM_ID not in ids
    assert all(item["finished"] is False for item in data)
    assert all(item["trainingId"] == TRAINING_ID for item in data)


def test_list_training_items_unknown_training_is_empty(client, analyst_headers):
    """GET /training/<id>/items returns an empty list for an unknown training."""
    response = client.get("/training/888888/items", headers=analyst_headers)

    assert response.status_code == 200
    assert response.get_json()["data"] == []


# --- POST /training/item/<id>/finish ---


def test_finish_item_does_not_complete_module_while_items_remain(
    client, analyst_headers
):
    """Finishing one of two items does not mark the whole module as finished."""
    response = client.post(
        f"/training/item/{ITEM_1_ID}/finish",
        json={"durationSeconds": 30},
        headers=analyst_headers,
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["moduleFinished"] is False

    # the finished item is now reflected in the counts and item flags
    list_data = client.get("/training/list", headers=analyst_headers).get_json()["data"]
    assert _find_training(list_data, TRAINING_ID)["totalLessonsFinished"] == 1

    items = client.get(
        f"/training/{TRAINING_ID}/items", headers=analyst_headers
    ).get_json()["data"]
    finished_flags = {item["id"]: item["finished"] for item in items}
    assert finished_flags[ITEM_1_ID] is True
    assert finished_flags[ITEM_2_ID] is False


def test_finishing_all_items_completes_module(client, analyst_headers):
    """Finishing every active item marks the module as finished exactly once."""
    first = client.post(
        f"/training/item/{ITEM_1_ID}/finish", json={}, headers=analyst_headers
    )
    assert first.get_json()["data"]["moduleFinished"] is False

    second = client.post(
        f"/training/item/{ITEM_2_ID}/finish", json={}, headers=analyst_headers
    )
    assert second.status_code == 200
    assert second.get_json()["data"]["moduleFinished"] is True

    # the module is now reported as finished in the listing
    list_data = client.get("/training/list", headers=analyst_headers).get_json()["data"]
    training = _find_training(list_data, TRAINING_ID)
    assert training["totalLessonsFinished"] == 2
    assert training["finished"] is True


def test_finishing_completed_module_again_returns_false(client, analyst_headers):
    """Re-finishing the last item does not re-complete an already finished module."""
    client.post(
        f"/training/item/{ITEM_1_ID}/finish", json={}, headers=analyst_headers
    )
    client.post(
        f"/training/item/{ITEM_2_ID}/finish", json={}, headers=analyst_headers
    )

    # item 2 finished a second time: the module was already completed
    again = client.post(
        f"/training/item/{ITEM_2_ID}/finish", json={}, headers=analyst_headers
    )

    assert again.status_code == 200
    assert again.get_json()["data"]["moduleFinished"] is False


def test_finish_item_requires_basic_features_permission(client):
    """POST finish returns 401 for a role without READ_BASIC_FEATURES."""
    headers = make_headers(
        get_access(client, roles=[Role.SUPPORT_REQUESTER.value])
    )
    response = client.post(
        f"/training/item/{ITEM_1_ID}/finish", json={}, headers=headers
    )

    assert response.status_code == 401
