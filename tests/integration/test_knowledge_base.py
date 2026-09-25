"""Tests: /knowledge-base endpoints and the article search of the N0 agent

Maintainers (WRITE_KNOWLEDGE_BASE) write the help articles inside NoHarm: an
article has a body (HTML from the editor), a link to an external page, or both,
and is pinned to whole screens (``path``) and/or to sections of a screen
(``section``). Readers open an article by id, but only once it is active: an
inactive article is a draft only maintainers can see.

``search`` is what the N0 agent reads instead of the ODOO vector index, so its
behaviour is pinned down here against the real full-text configuration: any
word of the question counts, accents do not matter, the title weighs more than
the body and inactive articles never come back.

An article can also point to training lessons that complement it: readers only
see the lessons of the modules their schema has access to (the training
center's own visibility rule), maintainers see them all.

``public.base_conhecimento`` is global, shared by every client: every row these
tests write has a title starting with ``ZZTest KB`` and is removed on the way in
and on the way out. The training modules/lessons use ids 991000+ (the training
tests use 990000+).

The test database has no n0-agent configuration, so saving never reaches the
vector index: the response reports it as disabled (the indexing itself is
covered by tests/unit/test_knowledge_base_vector_service.py).
"""

import pytest
from sqlalchemy import text

from repository import knowledge_base_repository
from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit
from utils import status

TITLE_PREFIX = "ZZTest KB"


def _remove_test_articles():
    """Drop every article these tests wrote."""
    session.execute(
        text("DELETE FROM public.base_conhecimento WHERE titulo LIKE :prefix"),
        {"prefix": f"{TITLE_PREFIX}%"},
    )
    session_commit()


@pytest.fixture(autouse=True)
def clean_articles():
    """Remove the test articles before and after each test."""
    _remove_test_articles()
    try:
        yield
    finally:
        session.rollback()
        _remove_test_articles()


# training fixtures: a global module, a module of another schema and an
# inactive lesson
GLOBAL_TRAINING = 991001
OTHER_SCHEMA_TRAINING = 991002
LESSON_GLOBAL = 991001
LESSON_OTHER_SCHEMA = 991002
LESSON_INACTIVE = 991003
_TRAINING_IDS = [GLOBAL_TRAINING, OTHER_SCHEMA_TRAINING]


def _remove_training():
    """Drop the seeded training modules and lessons."""
    params = {"ids": _TRAINING_IDS}
    for table in ("treinamento_item", "treinamento_esquema", "treinamento"):
        session.execute(
            text(f"DELETE FROM public.{table} WHERE idtreinamento = ANY(:ids)"), params
        )
    session_commit()


@pytest.fixture
def lessons():
    """Seed the training modules/lessons the articles can point to."""
    _remove_training()
    try:
        for id_training, position, scope in (
            (GLOBAL_TRAINING, 1, "global"),
            (OTHER_SCHEMA_TRAINING, 2, "schemas"),
        ):
            session.execute(
                text(
                    "INSERT INTO public.treinamento (idtreinamento, pagina, titulo, "
                    "posicao, ativo, obrigatorio, escopo, audiencia, tempo_horas, "
                    "created_at, created_by) VALUES (:id, :pagina, :titulo, :posicao, "
                    "true, false, :escopo, 'all', 0, now(), 1)"
                ),
                {
                    "id": id_training,
                    "pagina": ["ZZTest"],
                    "titulo": f"ZZTest Módulo {id_training}",
                    "posicao": position,
                    "escopo": scope,
                },
            )
        session.execute(
            text(
                "INSERT INTO public.treinamento_esquema (idtreinamento, schema_name, "
                "obrigatorio, created_at, created_by) "
                "VALUES (:id, 'outro_hospital', false, now(), 1)"
            ),
            {"id": OTHER_SCHEMA_TRAINING},
        )
        for id_lesson, id_training, active in (
            (LESSON_GLOBAL, GLOBAL_TRAINING, True),
            (LESSON_OTHER_SCHEMA, OTHER_SCHEMA_TRAINING, True),
            (LESSON_INACTIVE, GLOBAL_TRAINING, False),
        ):
            session.execute(
                text(
                    "INSERT INTO public.treinamento_item (idtreinamento_item, "
                    "idtreinamento, titulo, posicao, ativo, created_at, created_by) "
                    "VALUES (:id, :training, :titulo, 1, :ativo, now(), 1)"
                ),
                {
                    "id": id_lesson,
                    "training": id_training,
                    "titulo": f"ZZTest Aula {id_lesson}",
                    "ativo": active,
                },
            )
        session_commit()

        yield
    finally:
        session.rollback()
        # articles first: nothing references the lessons, but keep it tidy
        _remove_test_articles()
        _remove_training()


def _article(**overrides):
    """A valid upsert payload."""
    payload = {
        "title": f"{TITLE_PREFIX} Checagem de prescrição",
        "description": "Como checar uma prescrição",
        "path": ["Prescrição"],
        "section": ["prescricao.exames"],
        "content": "<p>Clique em <strong>Checar</strong> para concluir.</p>",
        "active": True,
    }
    payload.update(overrides)

    return payload


def _create(client, headers, **overrides):
    """Create an article through the API and return its payload."""
    response = client.post(
        "/knowledge-base/upsert", json=_article(**overrides), headers=headers
    )
    assert response.status_code == status.HTTP_200_OK, response.get_json()

    return response.get_json()["data"]


# --- permissions -------------------------------------------------------------


def test_upsert_requires_write_knowledge_base(client, analyst_headers):
    """POST /knowledge-base/upsert - readers cannot write [401]"""
    response = client.post(
        "/knowledge-base/upsert", json=_article(), headers=analyst_headers
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_list_requires_write_knowledge_base(client, analyst_headers):
    """POST /knowledge-base/list - the maintenance list is for maintainers [401]"""
    response = client.post("/knowledge-base/list", json={}, headers=analyst_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_get_requires_read_basic_features(client, curator_headers):
    """GET /knowledge-base/<id> - users without READ_BASIC_FEATURES are denied"""
    article = _create(client, curator_headers)
    headers = make_headers(get_access(client, roles=[Role.DISPENSING_MANAGER.value]))

    response = client.get(f"/knowledge-base/{article['id']}", headers=headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# --- create / update ---------------------------------------------------------


def test_create_article_with_content(client, curator_headers):
    """POST /knowledge-base/upsert - creates the article and returns it"""
    article = _create(client, curator_headers)

    assert article["id"] is not None
    assert article["title"] == f"{TITLE_PREFIX} Checagem de prescrição"
    assert article["path"] == ["Prescrição"]
    assert article["section"] == ["prescricao.exames"]
    assert article["link"] is None
    assert article["hasContent"] is True
    assert "<strong>Checar</strong>" in article["content"]
    assert article["createdAt"] is not None
    assert article["updatedAt"] is None


def test_update_article(client, curator_headers):
    """POST /knowledge-base/upsert - with an id, updates that article"""
    article = _create(client, curator_headers)

    updated = _create(
        client,
        curator_headers,
        id=article["id"],
        title=f"{TITLE_PREFIX} Novo título",
        section=[],
        active=False,
    )

    assert updated["id"] == article["id"]
    assert updated["title"] == f"{TITLE_PREFIX} Novo título"
    assert updated["section"] == []
    assert updated["active"] is False
    assert updated["updatedAt"] is not None


def test_update_unknown_article(client, curator_headers):
    """POST /knowledge-base/upsert - an unknown id is rejected [400]"""
    response = client.post(
        "/knowledge-base/upsert", json=_article(id=987654321), headers=curator_headers
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_article_needs_content_or_link(client, curator_headers):
    """POST /knowledge-base/upsert - an article with neither body nor link [400]"""
    response = client.post(
        "/knowledge-base/upsert",
        json=_article(content="   ", link=None),
        headers=curator_headers,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_link_only_article(client, curator_headers):
    """POST /knowledge-base/upsert - an article may only point elsewhere"""
    article = _create(
        client, curator_headers, content=None, link="https://kb.example.com/artigo"
    )

    assert article["hasContent"] is False
    assert article["link"] == "https://kb.example.com/artigo"


@pytest.mark.parametrize(
    "link", ["javascript:alert(1)", "data:text/html,oi", "kb.example.com/artigo"]
)
def test_link_must_be_http(client, curator_headers, link):
    """POST /knowledge-base/upsert - the panel opens the link: http(s) only [400]"""
    response = client.post(
        "/knowledge-base/upsert", json=_article(link=link), headers=curator_headers
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


# --- read --------------------------------------------------------------------


def test_reader_opens_an_active_article(client, curator_headers, analyst_headers):
    """GET /knowledge-base/<id> - readers get the body of an active article"""
    article = _create(client, curator_headers)

    response = client.get(f"/knowledge-base/{article['id']}", headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["content"] == article["content"]


def test_reader_cannot_open_a_draft(client, curator_headers, analyst_headers):
    """GET /knowledge-base/<id> - an inactive article is hidden from readers"""
    article = _create(client, curator_headers, active=False)

    reader = client.get(f"/knowledge-base/{article['id']}", headers=analyst_headers)
    maintainer = client.get(f"/knowledge-base/{article['id']}", headers=curator_headers)

    assert reader.status_code == status.HTTP_400_BAD_REQUEST
    assert maintainer.status_code == status.HTTP_200_OK


def test_maintenance_list_filters(client, curator_headers):
    """POST /knowledge-base/list - every article, filtered, without the body"""
    _create(client, curator_headers)
    _create(
        client,
        curator_headers,
        title=f"{TITLE_PREFIX} Relatório de intervenções",
        description=None,
        path=["Relatório: Intervenções"],
        section=[],
        active=False,
    )

    everything = client.post(
        "/knowledge-base/list", json={"term": TITLE_PREFIX}, headers=curator_headers
    ).get_json()["data"]
    by_section = client.post(
        "/knowledge-base/list",
        json={"term": TITLE_PREFIX, "section": ["prescricao.exames"]},
        headers=curator_headers,
    ).get_json()["data"]
    inactive = client.post(
        "/knowledge-base/list",
        json={"term": TITLE_PREFIX, "active": False},
        headers=curator_headers,
    ).get_json()["data"]

    assert [a["title"] for a in everything] == [
        f"{TITLE_PREFIX} Checagem de prescrição",
        f"{TITLE_PREFIX} Relatório de intervenções",
    ]
    assert all("content" not in a for a in everything)
    assert [a["title"] for a in by_section] == [
        f"{TITLE_PREFIX} Checagem de prescrição"
    ]
    assert [a["title"] for a in inactive] == [
        f"{TITLE_PREFIX} Relatório de intervenções"
    ]


# --- search (N0 agent) -------------------------------------------------------


def _search(client, query, limit=10):
    """Run the repository search inside an app context, keeping test rows only."""
    from mobile import app

    with app.app_context():
        return [
            kb.title
            for kb in knowledge_base_repository.search(query=query, limit=limit)
            if kb.title.startswith(TITLE_PREFIX)
        ]


def test_search_matches_any_word_ignoring_accents(client, curator_headers):
    """search - a question without accents finds the accented article"""
    _create(client, curator_headers)

    assert _search(client, "como faco a checagem da prescricao?") == [
        f"{TITLE_PREFIX} Checagem de prescrição"
    ]


def test_search_reads_the_body_without_markup(client, curator_headers):
    """search - words of the body match, HTML tags do not"""
    _create(client, curator_headers)

    assert _search(client, "concluir") == [f"{TITLE_PREFIX} Checagem de prescrição"]
    assert _search(client, "strong") == []


def test_search_ranks_title_matches_first(client, curator_headers):
    """search - a word in the title outranks the same word in the body"""
    _create(
        client,
        curator_headers,
        title=f"{TITLE_PREFIX} Configurar alertas",
        description=None,
        content="<p>Tela de configuração.</p>",
    )
    _create(
        client,
        curator_headers,
        title=f"{TITLE_PREFIX} Tela inicial",
        description=None,
        content="<p>Os alertas aparecem aqui.</p>",
    )

    assert _search(client, "alertas") == [
        f"{TITLE_PREFIX} Configurar alertas",
        f"{TITLE_PREFIX} Tela inicial",
    ]


def test_search_skips_inactive_articles(client, curator_headers):
    """search - drafts are never handed to the agent"""
    _create(client, curator_headers, active=False)

    assert _search(client, "checagem") == []


def test_search_without_words(client):
    """search - a question with no searchable word returns nothing"""
    assert _search(client, "?! ...") == []


# --- training lessons --------------------------------------------------------


def test_training_lessons_for_the_form(client, curator_headers, lessons):
    """GET /knowledge-base/training-lessons - active lessons of active modules"""
    response = client.get("/knowledge-base/training-lessons", headers=curator_headers)

    assert response.status_code == status.HTTP_200_OK
    seeded = [
        item
        for item in response.get_json()["data"]
        if item["trainingId"] in _TRAINING_IDS
    ]
    assert [item["id"] for item in seeded] == [LESSON_GLOBAL, LESSON_OTHER_SCHEMA]
    assert seeded[0] == {
        "id": LESSON_GLOBAL,
        "title": f"ZZTest Aula {LESSON_GLOBAL}",
        "trainingId": GLOBAL_TRAINING,
        "trainingTitle": f"ZZTest Módulo {GLOBAL_TRAINING}",
    }


def test_training_lessons_require_write_knowledge_base(client, analyst_headers):
    """GET /knowledge-base/training-lessons - readers are denied [401]"""
    response = client.get("/knowledge-base/training-lessons", headers=analyst_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_article_relates_lessons(client, curator_headers, lessons):
    """POST /knowledge-base/upsert - lessons are stored and come back resolved"""
    article = _create(
        client, curator_headers, training_items=[LESSON_OTHER_SCHEMA, LESSON_GLOBAL]
    )

    assert article["trainingItems"] == [LESSON_OTHER_SCHEMA, LESSON_GLOBAL]
    # in the training center order, whatever order they were picked in
    assert [lesson["id"] for lesson in article["trainingLessons"]] == [
        LESSON_GLOBAL,
        LESSON_OTHER_SCHEMA,
    ]


@pytest.mark.parametrize("lesson", [LESSON_INACTIVE, 987654321])
def test_article_rejects_unknown_or_inactive_lessons(
    client, curator_headers, lessons, lesson
):
    """POST /knowledge-base/upsert - only existing, active lessons [400]"""
    response = client.post(
        "/knowledge-base/upsert",
        json=_article(training_items=[LESSON_GLOBAL, lesson]),
        headers=curator_headers,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_reader_sees_only_the_lessons_of_their_schema(
    client, curator_headers, analyst_headers, lessons
):
    """GET /knowledge-base/<id> - a module of another schema is left out for
    readers, while maintainers see every lesson"""
    article = _create(
        client, curator_headers, training_items=[LESSON_GLOBAL, LESSON_OTHER_SCHEMA]
    )

    reader = client.get(f"/knowledge-base/{article['id']}", headers=analyst_headers)
    maintainer = client.get(f"/knowledge-base/{article['id']}", headers=curator_headers)

    assert [x["id"] for x in reader.get_json()["data"]["trainingLessons"]] == [
        LESSON_GLOBAL
    ]
    assert [x["id"] for x in maintainer.get_json()["data"]["trainingLessons"]] == [
        LESSON_GLOBAL,
        LESSON_OTHER_SCHEMA,
    ]


def test_lesson_deactivated_later_disappears(client, curator_headers, lessons):
    """GET /knowledge-base/<id> - a lesson deactivated after being related is
    no longer offered, though the relation is kept"""
    article = _create(client, curator_headers, training_items=[LESSON_GLOBAL])
    session.execute(
        text(
            "UPDATE public.treinamento_item SET ativo = false "
            "WHERE idtreinamento_item = :id"
        ),
        {"id": LESSON_GLOBAL},
    )
    session_commit()

    data = client.get(
        f"/knowledge-base/{article['id']}", headers=curator_headers
    ).get_json()["data"]

    assert data["trainingLessons"] == []
    assert data["trainingItems"] == [LESSON_GLOBAL]


# --- vector index ------------------------------------------------------------


def test_save_reports_the_vector_index_status(client, curator_headers):
    """POST /knowledge-base/upsert - without an n0 index, indexing is disabled"""
    article = _create(client, curator_headers)

    assert article["vectorIndex"] == "disabled"


def test_reindex_article(client, curator_headers, analyst_headers):
    """POST /knowledge-base/<id>/reindex - maintainers only"""
    article = _create(client, curator_headers)

    denied = client.post(
        f"/knowledge-base/{article['id']}/reindex", headers=analyst_headers
    )
    response = client.post(
        f"/knowledge-base/{article['id']}/reindex", headers=curator_headers
    )

    assert denied.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == {
        "id": article["id"],
        "vectorIndex": "disabled",
    }


# --- knowledge base page (every user) ----------------------------------------


def _browse(client, headers, **payload):
    """POST /knowledge-base/articles, keeping only the test articles."""
    response = client.post("/knowledge-base/articles", json=payload, headers=headers)
    assert response.status_code == status.HTTP_200_OK

    return [
        article
        for article in response.get_json()["data"]
        if article["title"].startswith(TITLE_PREFIX)
    ]


def test_browse_lists_the_published_articles(client, curator_headers, analyst_headers):
    """POST /knowledge-base/articles - published articles only, by title,
    without the body or the maintenance fields"""
    _create(client, curator_headers, title=f"{TITLE_PREFIX} B Relatórios")
    _create(client, curator_headers, title=f"{TITLE_PREFIX} A Prescrição")
    _create(client, curator_headers, title=f"{TITLE_PREFIX} C Rascunho", active=False)

    articles = _browse(client, analyst_headers)

    assert [a["title"] for a in articles] == [
        f"{TITLE_PREFIX} A Prescrição",
        f"{TITLE_PREFIX} B Relatórios",
    ]
    assert "content" not in articles[0]
    assert "active" not in articles[0]
    assert articles[0]["path"] == ["Prescrição"]
    assert articles[0]["hasContent"] is True


def test_browse_searches_like_the_agent(client, curator_headers, analyst_headers):
    """POST /knowledge-base/articles - a term runs the accent insensitive full
    text search, best match first, drafts excluded"""
    _create(
        client,
        curator_headers,
        title=f"{TITLE_PREFIX} Tela inicial",
        description=None,
        content="<p>As intervenções aparecem aqui.</p>",
    )
    _create(
        client,
        curator_headers,
        title=f"{TITLE_PREFIX} Registrar intervenções",
        description=None,
        content="<p>Passo a passo.</p>",
    )
    _create(
        client,
        curator_headers,
        title=f"{TITLE_PREFIX} Intervenção antiga",
        active=False,
    )
    _create(client, curator_headers, title=f"{TITLE_PREFIX} Outro assunto")

    articles = _browse(client, analyst_headers, term="intervencoes")

    assert [a["title"] for a in articles] == [
        f"{TITLE_PREFIX} Registrar intervenções",
        f"{TITLE_PREFIX} Tela inicial",
    ]


def test_browse_blank_term_lists_everything(client, curator_headers, analyst_headers):
    """POST /knowledge-base/articles - a blank term is no search"""
    _create(client, curator_headers)

    assert len(_browse(client, analyst_headers, term="   ")) == 1


def test_browse_requires_read_basic_features(client):
    """POST /knowledge-base/articles - no READ_BASIC_FEATURES, no page [401]"""
    headers = make_headers(get_access(client, roles=[Role.DISPENSING_MANAGER.value]))

    response = client.post("/knowledge-base/articles", json={}, headers=headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
