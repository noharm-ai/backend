"""Integration tests for the training feature (list / items / finish flow, plus
schema scope and audience targeting).

The seed database ships with no training data, so these tests create their own
training module (ids >= 990000, in the shared ``public`` schema) and remove it
afterwards. Completion records are written for the ``demo`` user (id 1), which
is the user behind the ``analyst_headers`` fixture; that user's schema is
``demo``, which is what schema-scoped modules are targeted at here.
"""

import pytest
from sqlalchemy import text

from config import Config
from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit

TRAINING_ID = 990001
INACTIVE_TRAINING_ID = 990002
EXTRA_TRAINING_ID = 990003
ITEM_1_ID = 990001
ITEM_2_ID = 990002
INACTIVE_ITEM_ID = 990003
EXTRA_ITEM_ID = 990004
DEMO_USER_ID = 1
DEMO_SCHEMA = "demo"
OTHER_SCHEMA = "outro"


def _add_training(
    training_id,
    position,
    active=True,
    mandatory=False,
    scope="global",
    audience="all",
    total_hours=0,
):
    """Insert a training module in the public schema (``pagina`` is an array)."""
    session.execute(
        text(
            "INSERT INTO public.treinamento "
            "(idtreinamento, pagina, titulo, resumo, posicao, ativo, obrigatorio, "
            "escopo, audiencia, tempo_horas, created_at, created_by) "
            "VALUES (:id, :pagina, :titulo, :resumo, :posicao, :ativo, :obrigatorio, "
            ":escopo, :audiencia, :tempo_horas, now(), :created_by)"
        ),
        {
            "id": training_id,
            "pagina": ["page-%d" % training_id],
            "titulo": "Training %d" % training_id,
            "resumo": "Description %d" % training_id,
            "posicao": position,
            "ativo": active,
            "obrigatorio": mandatory,
            "escopo": scope,
            "audiencia": audience,
            "tempo_horas": total_hours,
            "created_by": DEMO_USER_ID,
        },
    )


def _add_training_schema(training_id, schema_name, mandatory):
    """Target a scope='schemas' module at one schema."""
    session.execute(
        text(
            "INSERT INTO public.treinamento_esquema "
            "(idtreinamento, schema_name, obrigatorio, created_at, created_by) "
            "VALUES (:id, :schema_name, :obrigatorio, now(), :created_by)"
        ),
        {
            "id": training_id,
            "schema_name": schema_name,
            "obrigatorio": mandatory,
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
    session.execute(
        text("DELETE FROM public.treinamento_esquema WHERE idtreinamento >= 990000")
    )
    _set_onboarding_attribute(None)


def _set_onboarding_attribute(value):
    """Set (or remove, when value is None) the user's onboarding attribute. Its
    mere presence is what marks the user as new for audiencia='new_users'."""
    session.execute(
        text(
            "DELETE FROM public.usuario_atributo "
            "WHERE idusuario = :uid AND tipo = 'onboarding'"
        ),
        {"uid": DEMO_USER_ID},
    )

    if value is not None:
        session.execute(
            text(
                "INSERT INTO public.usuario_atributo "
                "(idusuario, tipo, valor, created_at, created_by) "
                "VALUES (:uid, 'onboarding', :value, now(), :uid)"
            ),
            {"uid": DEMO_USER_ID, "value": value},
        )

    session_commit()


@pytest.fixture(scope="module", autouse=True)
def seed_training():
    """Create a training module with active/inactive rows, tear it down after."""
    _clear_user_progress()
    session.execute(text("DELETE FROM public.treinamento_item WHERE idtreinamento_item >= 990000"))
    session.execute(text("DELETE FROM public.treinamento WHERE idtreinamento >= 990000"))
    session_commit()

    # mirrors the real basic training: global, mandatory, new users only
    _add_training(
        TRAINING_ID,
        position=10,
        active=True,
        mandatory=True,
        scope="global",
        audience="new_users",
    )
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
def feature_enabled(monkeypatch):
    """Obligations are gated by FEATURE_USER_ONBOARDING, which is off by default
    in the test environment. Tests about the flag itself override this again."""
    monkeypatch.setattr(Config, "FEATURE_USER_ONBOARDING", True)


@pytest.fixture(autouse=True)
def reset_progress():
    """Each test starts with no completion recorded for the seeded training."""
    _clear_user_progress()
    yield
    _clear_user_progress()


@pytest.fixture
def module_factory():
    """Create extra modules (one lesson each) and clean them up afterwards."""
    created = []

    def _create(training_id, item_id, **kwargs):
        _add_training(training_id, position=50 + len(created), **kwargs)
        _add_item(item_id, training_id, position=1, active=True)
        created.append((training_id, item_id))
        session_commit()

    yield _create

    for training_id, item_id in created:
        for statement, params in (
            (
                "DELETE FROM public.treinamento_item_usuario "
                "WHERE idtreinamento_item = :item",
                {"item": item_id},
            ),
            (
                "DELETE FROM public.treinamento_usuario WHERE idtreinamento = :id",
                {"id": training_id},
            ),
            (
                "DELETE FROM public.treinamento_esquema WHERE idtreinamento = :id",
                {"id": training_id},
            ),
            (
                "DELETE FROM public.treinamento_item WHERE idtreinamento_item = :item",
                {"item": item_id},
            ),
            (
                "DELETE FROM public.treinamento WHERE idtreinamento = :id",
                {"id": training_id},
            ),
        ):
            session.execute(text(statement), params)
    session_commit()


def _find_training(data, training_id):
    """Return the seeded training entry from a /training/list payload."""
    return next((t for t in data if t["id"] == training_id), None)


def _list(client, headers):
    """GET /training/list payload."""
    return client.get("/training/list", headers=headers).get_json()["data"]


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
    assert training["certificateAvailable"] is False


def test_list_trainings_excludes_inactive_module(client, analyst_headers):
    """GET /training/list does not include inactive training modules."""
    response = client.get("/training/list", headers=analyst_headers)
    data = response.get_json()["data"]

    assert response.status_code == 200
    assert _find_training(data, INACTIVE_TRAINING_ID) is None


def test_list_trainings_requires_basic_features_permission(client):
    """GET /training/list returns 401 for a role without READ_BASIC_FEATURES."""
    headers = make_headers(
        get_access(client, roles=[Role.DISPENSING_MANAGER.value])
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
    assert training["certificateAvailable"] is True


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


def _validation_code(training_id, user_id=DEMO_USER_ID):
    """The validation code stored on a module's completion record."""
    return session.execute(
        text(
            "SELECT codigo_validacao FROM public.treinamento_usuario "
            "WHERE idtreinamento = :id AND idusuario = :uid"
        ),
        {"id": training_id, "uid": user_id},
    ).scalar()


def test_completing_a_module_stamps_a_validation_code(client, analyst_headers):
    """Completion writes the code the certificate is verified by.

    ``codigo_validacao`` is NOT NULL with a unique index, so a completion that
    left it unset would fail the insert instead of finishing the module.
    """
    _finish_module(client, analyst_headers)

    code = _validation_code(TRAINING_ID)

    assert code is not None
    assert len(code) == 12
    # the alphabet leaves out the characters that get confused when a code is
    # read off a printed certificate and typed back in
    assert set(code) <= set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")


def test_each_completion_gets_its_own_validation_code(
    client, analyst_headers, module_factory
):
    """Two modules finished by the same user do not share a code.

    The column is uniquely indexed, so a reused code would make the second
    completion fail outright.
    """
    module_factory(990019, 990019)

    _finish_module(client, analyst_headers)
    client.post("/training/item/990019/finish", json={}, headers=analyst_headers)

    assert _validation_code(TRAINING_ID) != _validation_code(990019)


def test_finish_item_requires_basic_features_permission(client):
    """POST finish returns 401 for a role without READ_BASIC_FEATURES."""
    headers = make_headers(
        get_access(client, roles=[Role.DISPENSING_MANAGER.value])
    )
    response = client.post(
        f"/training/item/{ITEM_1_ID}/finish", json={}, headers=headers
    )

    assert response.status_code == 401


# --- GET /training/<id>/certificate ---


def _finish_module(client, headers):
    """Finish both active items of the seeded training module."""
    client.post(f"/training/item/{ITEM_1_ID}/finish", json={}, headers=headers)
    client.post(f"/training/item/{ITEM_2_ID}/finish", json={}, headers=headers)


def test_certificate_for_finished_module(client, analyst_headers):
    """GET certificate returns the data needed to render one after completion."""
    _finish_module(client, analyst_headers)

    response = client.get(
        f"/training/{TRAINING_ID}/certificate", headers=analyst_headers
    )
    data = response.get_json()["data"]

    assert response.status_code == 200
    assert data["trainingId"] == TRAINING_ID
    assert data["trainingTitle"] == "Training %d" % TRAINING_ID
    assert data["totalLessons"] == 2
    assert data["userName"]
    assert data["completedAt"] is not None
    # the seeded module declares no workload, so nothing to print
    assert data["totalHours"] == 0


def test_certificate_reports_the_module_workload(
    client, analyst_headers, module_factory
):
    """A module with a declared carga horaria carries it on the certificate."""
    module_factory(990018, 990018, total_hours=8)

    client.post("/training/item/990018/finish", json={}, headers=analyst_headers)

    response = client.get("/training/990018/certificate", headers=analyst_headers)

    assert response.status_code == 200
    assert response.get_json()["data"]["totalHours"] == 8


def test_certificate_refused_while_lessons_are_pending(client, analyst_headers):
    """No certificate while any active lesson of the module is unfinished."""
    client.post(
        f"/training/item/{ITEM_1_ID}/finish", json={}, headers=analyst_headers
    )

    response = client.get(
        f"/training/{TRAINING_ID}/certificate", headers=analyst_headers
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.trainingNotFinished"


def test_certificate_for_unknown_module_is_refused(client, analyst_headers):
    """GET certificate returns 400 for a training id that does not exist."""
    response = client.get("/training/888888/certificate", headers=analyst_headers)

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.invalidRecord"


def test_certificate_requires_the_completion_record(client, analyst_headers):
    """The treinamento_usuario record is the single proof of completion:
    without it there is no certificate, whatever the lesson counts say."""
    _finish_module(client, analyst_headers)
    session.execute(
        text(
            "DELETE FROM public.treinamento_usuario "
            "WHERE idtreinamento = :id AND idusuario = :uid"
        ),
        {"id": TRAINING_ID, "uid": DEMO_USER_ID},
    )
    session_commit()

    response = client.get(
        f"/training/{TRAINING_ID}/certificate", headers=analyst_headers
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.trainingNotFinished"


def test_certificate_survives_new_lessons_added_after_completion(
    client, analyst_headers, module_factory
):
    """Publishing extra lessons reopens the module but never revokes the
    certificate: the completion record alone decides eligibility."""
    module_factory(990016, 990016, mandatory=False, scope="global", audience="all")

    finish = client.post(
        "/training/item/990016/finish", json={}, headers=analyst_headers
    )
    assert finish.get_json()["data"]["moduleFinished"] is True

    # a new lesson ships after the user already finished the module
    _add_item(990017, 990016, position=2, active=True)
    session_commit()

    training = _find_training(_list(client, analyst_headers), 990016)
    assert training["finished"] is False
    assert training["certificateAvailable"] is True

    response = client.get("/training/990016/certificate", headers=analyst_headers)
    data = response.get_json()["data"]

    assert response.status_code == 200
    assert data["completedAt"] is not None
    # the certificate reports what the user completed back then
    assert data["totalLessons"] == 1

    session.execute(
        text("DELETE FROM public.treinamento_item WHERE idtreinamento_item = 990017")
    )
    session_commit()


def test_certificate_survives_module_deactivation(client, analyst_headers):
    """Deactivating a module must not void certificates already earned."""
    session.execute(
        text(
            "INSERT INTO public.treinamento_usuario "
            "(idtreinamento, idusuario, codigo_validacao, created_at) "
            "VALUES (:id, :uid, :code, now())"
        ),
        {
            "id": INACTIVE_TRAINING_ID,
            "uid": DEMO_USER_ID,
            "code": "ZZTESTINACT1",
        },
    )
    session_commit()

    response = client.get(
        f"/training/{INACTIVE_TRAINING_ID}/certificate", headers=analyst_headers
    )
    data = response.get_json()["data"]

    assert response.status_code == 200
    assert data["trainingTitle"] == "Training %d" % INACTIVE_TRAINING_ID


def test_certificate_requires_basic_features_permission(client):
    """GET certificate returns 401 for a role without READ_BASIC_FEATURES."""
    headers = make_headers(
        get_access(client, roles=[Role.DISPENSING_MANAGER.value])
    )
    response = client.get(f"/training/{TRAINING_ID}/certificate", headers=headers)

    assert response.status_code == 401




# --- schema scope and audience targeting ---
#
# Effective mandatory-ness is computed in exactly one place
# (training_service._list_user_trainings), so asserting the `mandatory` flag of
# GET /training/list also pins what the login summary will report.


def test_global_module_is_mandatory_everywhere(client, analyst_headers, module_factory):
    """scope='global' + obrigatorio + audiencia='all' is mandatory for anyone."""
    module_factory(990010, 990010, mandatory=True, scope="global", audience="all")

    training = _find_training(_list(client, analyst_headers), 990010)

    assert training is not None
    assert training["mandatory"] is True


def test_schema_scoped_module_is_mandatory_in_the_targeted_schema(
    client, analyst_headers, module_factory
):
    """scope='schemas' takes its mandatory flag from the row for that schema."""
    module_factory(990011, 990011, mandatory=False, scope="schemas", audience="all")
    _add_training_schema(990011, DEMO_SCHEMA, mandatory=True)
    session_commit()

    training = _find_training(_list(client, analyst_headers), 990011)

    assert training is not None
    # obrigatorio on the module itself is false; the schema row wins
    assert training["mandatory"] is True


def test_schema_row_can_make_a_module_optional(
    client, analyst_headers, module_factory
):
    """A schema row with obrigatorio=false keeps the module visible but optional."""
    module_factory(990012, 990012, mandatory=True, scope="schemas", audience="all")
    _add_training_schema(990012, DEMO_SCHEMA, mandatory=False)
    session_commit()

    training = _find_training(_list(client, analyst_headers), 990012)

    assert training is not None
    assert training["mandatory"] is False


def test_module_targeting_another_schema_is_invisible(
    client, analyst_headers, module_factory
):
    """scope='schemas' with a row for a different schema is not listed at all."""
    module_factory(990013, 990013, mandatory=True, scope="schemas", audience="all")
    _add_training_schema(990013, OTHER_SCHEMA, mandatory=True)
    session_commit()

    assert _find_training(_list(client, analyst_headers), 990013) is None


def test_schema_scoped_module_without_rows_is_invisible(
    client, analyst_headers, module_factory
):
    """Fail closed: no schema rows means no schema, not every schema."""
    module_factory(990014, 990014, mandatory=True, scope="schemas", audience="all")

    assert _find_training(_list(client, analyst_headers), 990014) is None


def test_new_users_audience_is_optional_for_a_pre_existing_user(
    client, analyst_headers
):
    """audiencia='new_users' is visible but not mandatory without an onboarding row."""
    _set_onboarding_attribute(None)

    training = _find_training(_list(client, analyst_headers), TRAINING_ID)

    assert training is not None
    assert training["mandatory"] is False


def test_new_users_audience_is_mandatory_for_a_new_user(client, analyst_headers):
    """The presence of the onboarding row is what makes it mandatory."""
    _set_onboarding_attribute("pending")

    training = _find_training(_list(client, analyst_headers), TRAINING_ID)

    assert training["mandatory"] is True


# --- mandatory summary ---


def test_finish_returns_the_recomputed_mandatory_summary(client, analyst_headers):
    """The finish response carries the counts the header renders."""
    _set_onboarding_attribute("pending")

    first = client.post(
        f"/training/item/{ITEM_1_ID}/finish", json={}, headers=analyst_headers
    )
    assert first.get_json()["data"]["training"] == {
        "mandatoryTotal": 1,
        "mandatoryFinished": 0,
    }

    second = client.post(
        f"/training/item/{ITEM_2_ID}/finish", json={}, headers=analyst_headers
    )
    assert second.get_json()["data"]["moduleFinished"] is True
    assert second.get_json()["data"]["training"] == {
        "mandatoryTotal": 1,
        "mandatoryFinished": 1,
    }


def test_summary_grows_when_another_mandatory_module_is_published(
    client, analyst_headers, module_factory
):
    """The count is derived, so a newly published module re-nags a finished user.

    This is the case the previous cached usuario_atributo design could not
    express: once a user was 'completed' they were never counted again.
    """
    _set_onboarding_attribute("pending")

    client.post(f"/training/item/{ITEM_1_ID}/finish", json={}, headers=analyst_headers)
    done = client.post(
        f"/training/item/{ITEM_2_ID}/finish", json={}, headers=analyst_headers
    )
    assert done.get_json()["data"]["training"]["mandatoryFinished"] == 1

    # a new feature ships with its own mandatory training
    module_factory(990015, 990015, mandatory=True, scope="global", audience="all")

    training = _find_training(_list(client, analyst_headers), 990015)
    assert training["mandatory"] is True
    assert training["finished"] is False

    mandatory = [t for t in _list(client, analyst_headers) if t["mandatory"]]
    assert len(mandatory) == 2
    assert len([t for t in mandatory if t["finished"]]) == 1


def test_pre_existing_user_owes_nothing_when_every_module_targets_new_users(
    client, analyst_headers
):
    """A veteran has no mandatory modules, so the header shows nothing."""
    _set_onboarding_attribute(None)

    assert [t for t in _list(client, analyst_headers) if t["mandatory"]] == []


# --- the env flag gates obligations, not content ---


def _authenticate(client):
    """Full /authenticate payload for the demo user (not just the token)."""
    return client.post(
        "/authenticate", json={"email": "demo", "password": "demo"}
    ).get_json()


def test_login_summary_is_zeroed_when_the_feature_flag_is_off(monkeypatch, client):
    """FEATURE_USER_ONBOARDING off means no obligations regardless of content."""
    _set_onboarding_attribute("pending")
    monkeypatch.setattr(Config, "FEATURE_USER_ONBOARDING", False)

    assert _authenticate(client)["training"] == {
        "mandatoryTotal": 0,
        "mandatoryFinished": 0,
    }


def test_login_summary_reports_obligations_when_the_feature_flag_is_on(
    monkeypatch, client
):
    """With the flag on the login payload reports the derived counts."""
    _set_onboarding_attribute("pending")
    monkeypatch.setattr(Config, "FEATURE_USER_ONBOARDING", True)

    assert _authenticate(client)["training"] == {
        "mandatoryTotal": 1,
        "mandatoryFinished": 0,
    }
