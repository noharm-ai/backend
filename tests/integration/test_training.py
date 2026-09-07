"""Integration tests for the training feature (list / items / finish flow, plus
schema scope and audience targeting).

The seed database ships with no training data, so these tests create their own
training module (ids >= 990000, in the shared ``public`` schema) and remove it
afterwards. Completion records are written for the ``demo`` user (id 1), which
is the user behind the ``analyst_headers`` fixture; that user's schema is
``demo``, which is what schema-scoped modules are targeted at here.
"""

import re

import pytest
from sqlalchemy import text

from config import Config
from exception.validation_error import ValidationError
from mobile import app
from repository import training_repository
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


CODE_PATTERN = r"^[0-9A-HJ-NP-TV-Z]{4}-[0-9A-HJ-NP-TV-Z]{4}-[0-9A-HJ-NP-TV-Z]{4}$"


def _issue_certificate(client, headers, training_id=TRAINING_ID):
    """Finish the seeded module and return its certificate payload."""
    _finish_module(client, headers)

    return client.get(
        f"/training/{training_id}/certificate", headers=headers
    ).get_json()["data"]


def test_certificate_carries_a_validation_code(client, analyst_headers):
    """Issuing a certificate mints the public validation code."""
    data = _issue_certificate(client, analyst_headers)

    assert re.match(CODE_PATTERN, data["validationCode"])


def test_validation_code_is_stable_across_prints(client, analyst_headers):
    """Re-printing must return the SAME code. A regression that re-mints on
    every print would silently invalidate every certificate already on paper."""
    first = _issue_certificate(client, analyst_headers)["validationCode"]

    second = client.get(
        f"/training/{TRAINING_ID}/certificate", headers=analyst_headers
    ).get_json()["data"]["validationCode"]

    assert first == second


def test_public_validation_needs_no_authentication(client, analyst_headers):
    """The whole point of the feature: no headers at all, and it answers."""
    code = _issue_certificate(client, analyst_headers)["validationCode"]

    response = client.get(f"/public/certificate/{code}")

    assert response.status_code == 200
    assert response.get_json()["data"]["valid"] is True


def test_public_validation_confirms_the_certificate(client, analyst_headers):
    """The confirmation carries what a validator needs to check against paper."""
    certificate = _issue_certificate(client, analyst_headers)

    data = client.get(
        f"/public/certificate/{certificate['validationCode']}"
    ).get_json()["data"]

    assert data["valid"] is True
    assert data["trainingTitle"] == certificate["trainingTitle"]
    assert data["totalLessons"] == certificate["totalLessons"]
    assert data["totalHours"] == certificate["totalHours"]
    assert data["completedAt"] == certificate["completedAt"]
    assert "*" in data["maskedName"]


def test_public_validation_lists_the_lessons_taken(client, analyst_headers):
    """The lessons themselves, in module order, so a validator sees what the
    certificate actually covered rather than just how many there were."""
    certificate = _issue_certificate(client, analyst_headers)

    data = client.get(
        f"/public/certificate/{certificate['validationCode']}"
    ).get_json()["data"]

    assert data["lessons"] == ["Item %d" % ITEM_1_ID, "Item %d" % ITEM_2_ID]
    # the count is derived from the list, so the two cannot drift apart
    assert data["totalLessons"] == len(data["lessons"])


def test_listed_lessons_survive_a_lesson_being_deactivated(
    client, analyst_headers
):
    """Deactivating a lesson must not rewrite history: the certificate reports
    what the user did, not the module's current content."""
    _finish_module(client, analyst_headers)
    certificate = client.get(
        f"/training/{TRAINING_ID}/certificate", headers=analyst_headers
    ).get_json()["data"]

    session.execute(
        text(
            "UPDATE public.treinamento_item SET ativo = false "
            "WHERE idtreinamento_item = :id"
        ),
        {"id": ITEM_2_ID},
    )
    session_commit()

    data = client.get(
        f"/public/certificate/{certificate['validationCode']}"
    ).get_json()["data"]

    assert data["lessons"] == ["Item %d" % ITEM_1_ID, "Item %d" % ITEM_2_ID]

    session.execute(
        text(
            "UPDATE public.treinamento_item SET ativo = true "
            "WHERE idtreinamento_item = :id"
        ),
        {"id": ITEM_2_ID},
    )
    session_commit()


def test_lessons_are_listed_in_module_order(client, analyst_headers):
    """Order follows the module's positions, not the order they were finished."""
    # finish the second lesson first
    client.post(f"/training/item/{ITEM_2_ID}/finish", json={}, headers=analyst_headers)
    client.post(f"/training/item/{ITEM_1_ID}/finish", json={}, headers=analyst_headers)

    certificate = client.get(
        f"/training/{TRAINING_ID}/certificate", headers=analyst_headers
    ).get_json()["data"]

    data = client.get(
        f"/public/certificate/{certificate['validationCode']}"
    ).get_json()["data"]

    assert data["lessons"] == ["Item %d" % ITEM_1_ID, "Item %d" % ITEM_2_ID]


def test_public_validation_never_leaks_the_full_name(client, analyst_headers):
    """A substring check on the raw body, so it also catches someone helpfully
    adding userName back to the payload."""
    certificate = _issue_certificate(client, analyst_headers)

    response = client.get(f"/public/certificate/{certificate['validationCode']}")
    body = response.get_data(as_text=True)

    assert certificate["userName"] not in body
    for leaked in ("userId", "trainingId", "email", "schema", "userName"):
        assert leaked not in response.get_json()["data"]


@pytest.mark.parametrize(
    "mangle",
    [
        lambda code: code.lower(),
        lambda code: code.replace("-", ""),
        lambda code: code.replace("-", " ").strip(),
    ],
)
def test_public_validation_normalizes_what_a_human_types(
    client, analyst_headers, mangle
):
    """Case and grouping are display concerns, not part of the code."""
    code = _issue_certificate(client, analyst_headers)["validationCode"]

    response = client.get(f"/public/certificate/{mangle(code)}")

    assert response.get_json()["data"]["valid"] is True


@pytest.mark.parametrize(
    "code", ["ZZZZ-ZZZZ-ZZZZ", "nope", "ABCD-EFGH-JKMN-PQRS"]
)
def test_public_validation_answers_valid_false_not_404(client, code):
    """Unknown and malformed codes get the same HTTP 200 / valid=False answer:
    a typo is the expected case on a public page, and one shape of response
    leaves no oracle separating 'well formed but unknown' from 'junk'."""
    response = client.get(f"/public/certificate/{code}")

    assert response.status_code == 200
    assert response.get_json()["data"] == {"valid": False}


def test_completing_a_module_mints_the_code_before_any_print(
    client, analyst_headers
):
    """The code belongs to the completion, not to the act of printing: it is
    already on the record before anyone asks for a certificate."""
    _finish_module(client, analyst_headers)

    record = session.execute(
        text(
            "SELECT codigo_validacao FROM public.treinamento_usuario "
            "WHERE idtreinamento = :id AND idusuario = :uid"
        ),
        {"id": TRAINING_ID, "uid": DEMO_USER_ID},
    ).first()

    assert record[0] is not None
    assert len(record[0]) == 12

    # and it is the same one the certificate goes on to print
    printed = client.get(
        f"/training/{TRAINING_ID}/certificate", headers=analyst_headers
    ).get_json()["data"]["validationCode"]

    assert printed.replace("-", "") == record[0]


def test_code_generation_refuses_rather_than_reusing_a_code(
    client, analyst_headers, monkeypatch
):
    """The single batched lookup is a real guard, not decoration: if every
    candidate were already taken it raises instead of writing a duplicate."""
    _finish_module(client, analyst_headers)

    existing = session.execute(
        text(
            "SELECT codigo_validacao FROM public.treinamento_usuario "
            "WHERE idtreinamento = :id AND idusuario = :uid"
        ),
        {"id": TRAINING_ID, "uid": DEMO_USER_ID},
    ).first()[0]

    # force every candidate to collide
    monkeypatch.setattr(
        training_repository.certificateutils, "generate_code", lambda: existing
    )

    with app.app_context():
        with pytest.raises(ValidationError):
            training_repository._generate_unique_validation_code()


def test_each_completion_gets_its_own_code(
    client, analyst_headers, module_factory
):
    """Two completions never share a code. The unique index depends on it, and
    so does the premise that a code identifies one certificate."""
    _finish_module(client, analyst_headers)
    module_factory(990019, 990019)
    client.post("/training/item/990019/finish", json={}, headers=analyst_headers)

    first = client.get(
        f"/training/{TRAINING_ID}/certificate", headers=analyst_headers
    ).get_json()["data"]["validationCode"]
    second = client.get(
        "/training/990019/certificate", headers=analyst_headers
    ).get_json()["data"]["validationCode"]

    assert first != second

    # and each resolves to its own module
    assert (
        client.get(f"/public/certificate/{first}").get_json()["data"][
            "trainingTitle"
        ]
        == "Training %d" % TRAINING_ID
    )
    assert (
        client.get(f"/public/certificate/{second}").get_json()["data"][
            "trainingTitle"
        ]
        == "Training 990019"
    )


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
            "code": "ZZZZZZZZZZZ9",
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


# --- GET /training/overview ---
#
# The manager overview resolves progress for many users at once, through its own
# set based queries, so these tests exist mostly to pin it against the per-user
# reading: whatever a user sees on their own Training Central page (and whatever
# the support-ticket gate enforces) is what the manager must read for them.


OVERVIEW_LESSON_ID = 990020


def _overview(client, headers):
    """GET /training/overview payload."""
    return client.get("/training/overview", headers=headers).get_json()["data"]


def _overview_user(data, user_id):
    """Return one user entry from an overview payload."""
    return next((u for u in data["users"] if u["id"] == user_id), None)


def _overview_module(entry, training_id):
    """Return one module entry from a user's overview entry."""
    return next((m for m in entry["modules"] if m["id"] == training_id), None)


@pytest.fixture
def extra_lesson():
    """Add a lesson to the seeded module after the fact, and remove it again.

    This is what "reopens" an already finished module: the completion record
    stays, the active-lesson count moves.
    """
    yield lambda: (
        _add_item(OVERVIEW_LESSON_ID, TRAINING_ID, position=4, active=True),
        session_commit(),
    )

    session.execute(
        text(
            "DELETE FROM public.treinamento_item_usuario "
            "WHERE idtreinamento_item = :item"
        ),
        {"item": OVERVIEW_LESSON_ID},
    )
    session.execute(
        text("DELETE FROM public.treinamento_item WHERE idtreinamento_item = :item"),
        {"item": OVERVIEW_LESSON_ID},
    )
    session_commit()


def test_overview_lists_the_schema_modules_and_its_users(client, user_manager_headers):
    """The payload carries the module catalogue and one entry per user."""
    response = client.get("/training/overview", headers=user_manager_headers)
    data = response.get_json()["data"]

    assert response.status_code == 200

    module = _find_training(data["modules"], TRAINING_ID)
    assert module is not None
    assert module["title"] == "Training %d" % TRAINING_ID
    assert module["audience"] == "new_users"

    entry = _overview_user(data, DEMO_USER_ID)
    assert entry is not None
    assert _overview_module(entry, TRAINING_ID) is not None


def test_overview_omits_inactive_modules(client, user_manager_headers):
    """An inactive module is out of the catalogue and out of every user entry."""
    data = _overview(client, user_manager_headers)

    assert _find_training(data["modules"], INACTIVE_TRAINING_ID) is None
    assert (
        _overview_module(_overview_user(data, DEMO_USER_ID), INACTIVE_TRAINING_ID)
        is None
    )


def test_overview_omits_modules_targeting_another_schema(
    client, user_manager_headers, module_factory
):
    """The visibility rule is shared with the per-user list: fail closed."""
    module_factory(990016, 990016, mandatory=True, scope="schemas", audience="all")
    _add_training_schema(990016, OTHER_SCHEMA, mandatory=True)
    session_commit()

    data = _overview(client, user_manager_headers)

    assert _find_training(data["modules"], 990016) is None
    assert _overview_module(_overview_user(data, DEMO_USER_ID), 990016) is None


def test_overview_counts_only_active_lessons(client, user_manager_headers):
    """The seeded module has two active lessons and one inactive one."""
    data = _overview(client, user_manager_headers)
    module = _overview_module(_overview_user(data, DEMO_USER_ID), TRAINING_ID)

    assert module["totalLessons"] == 2


def test_overview_starts_a_user_with_no_progress(client, user_manager_headers):
    """A user who never opened the training reads as untouched, not as missing."""
    entry = _overview_user(_overview(client, user_manager_headers), DEMO_USER_ID)
    module = _overview_module(entry, TRAINING_ID)

    assert module["totalLessonsFinished"] == 0
    assert module["finished"] is False
    assert module["completedAt"] is None
    assert entry["totalLessonsFinished"] == 0
    assert entry["lastActivityAt"] is None


def test_overview_follows_a_user_through_a_module(client, user_manager_headers):
    """Partial progress, then completion, as the manager would watch it happen."""
    _set_onboarding_attribute("pending")

    client.post(
        f"/training/item/{ITEM_1_ID}/finish", json={}, headers=user_manager_headers
    )

    entry = _overview_user(_overview(client, user_manager_headers), DEMO_USER_ID)
    module = _overview_module(entry, TRAINING_ID)
    assert module["totalLessonsFinished"] == 1
    assert module["finished"] is False
    assert module["completedAt"] is None
    assert entry["mandatoryFinished"] == 0
    assert entry["lastActivityAt"] is not None

    client.post(
        f"/training/item/{ITEM_2_ID}/finish", json={}, headers=user_manager_headers
    )

    entry = _overview_user(_overview(client, user_manager_headers), DEMO_USER_ID)
    module = _overview_module(entry, TRAINING_ID)
    assert module["totalLessonsFinished"] == 2
    assert module["finished"] is True
    assert module["completedAt"] is not None
    assert entry["mandatoryTotal"] == 1
    assert entry["mandatoryFinished"] == 1


def test_overview_mandatory_matches_the_users_own_page(client, user_manager_headers):
    """The invariant that matters: the manager must not read "done" for someone
    the support-ticket gate still considers pending.

    audiencia='new_users' is only mandatory for a user carrying the onboarding
    row, and both readings go through training_service._is_mandatory.
    """
    _set_onboarding_attribute(None)

    own = _find_training(_list(client, user_manager_headers), TRAINING_ID)
    entry = _overview_user(_overview(client, user_manager_headers), DEMO_USER_ID)

    assert own["mandatory"] is False
    assert _overview_module(entry, TRAINING_ID)["mandatory"] is False
    assert entry["newUser"] is False
    assert entry["mandatoryTotal"] == 0

    _set_onboarding_attribute("pending")

    own = _find_training(_list(client, user_manager_headers), TRAINING_ID)
    entry = _overview_user(_overview(client, user_manager_headers), DEMO_USER_ID)

    assert own["mandatory"] is True
    assert _overview_module(entry, TRAINING_ID)["mandatory"] is True
    assert entry["newUser"] is True
    assert entry["mandatoryTotal"] == 1


def test_overview_shows_a_reopened_module_as_pending_but_keeps_the_date(
    client, user_manager_headers, extra_lesson
):
    """A module that gained a lesson goes back to pending while completedAt
    stays: the certificate was earned, the module is not done again."""
    client.post(
        f"/training/item/{ITEM_1_ID}/finish", json={}, headers=user_manager_headers
    )
    client.post(
        f"/training/item/{ITEM_2_ID}/finish", json={}, headers=user_manager_headers
    )

    extra_lesson()

    module = _overview_module(
        _overview_user(_overview(client, user_manager_headers), DEMO_USER_ID),
        TRAINING_ID,
    )

    assert module["totalLessons"] == 3
    assert module["totalLessonsFinished"] == 2
    assert module["finished"] is False
    assert module["completedAt"] is not None


def test_overview_zeroes_obligations_when_the_feature_flag_is_off(
    monkeypatch, client, user_manager_headers
):
    """The flag gates obligations, not content: the modules are still listed and
    still tagged mandatory, nobody owes them."""
    _set_onboarding_attribute("pending")
    monkeypatch.setattr(Config, "FEATURE_USER_ONBOARDING", False)

    data = _overview(client, user_manager_headers)
    entry = _overview_user(data, DEMO_USER_ID)

    assert _find_training(data["modules"], TRAINING_ID) is not None
    assert _overview_module(entry, TRAINING_ID)["mandatory"] is True
    assert entry["mandatoryTotal"] == 0
    assert entry["mandatoryFinished"] == 0


def test_overview_requires_read_users_permission(client, analyst_headers):
    """PRESCRIPTION_ANALYST holds no READ_USERS, so the overview is out of reach."""
    response = client.get("/training/overview", headers=analyst_headers)

    assert response.status_code == 401
