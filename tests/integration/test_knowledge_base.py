"""Tests: /knowledge-base/* (the in-app help center)

The knowledge base page lists every published article, opens one with its HTML
content, related articles and related lessons, and runs a semantic search over
the vector index.

What matters here and is not obvious from the queries:
- ``ativo`` is what keeps a draft or retired article out of the product, on
  every endpoint, including when it is pointed at from another article or
  returned by the vector index;
- ``relacionados`` and ``aulas_relacionadas`` are curated lists, so their order
  is kept;
- a related lesson is only shown when the user's schema sees its module, or the
  page would link to a module the user cannot open;
- the index stores articles in chunks, so a search collapses them to one result
  per article.

Rows are seeded directly into the public tables with high ids; the vector
search is mocked.
"""

import json
from unittest.mock import patch

import pytest
from sqlalchemy import bindparam, text

from models.enums import GlobalMemoryEnum
from services import knowledge_base_service
from tests.conftest import session, session_commit
from utils import status

DEMO_USER_ID = 1
OTHER_SCHEMA = "outro"

ARTICLE_ID = 993101
RELATED_A_ID = 993102
RELATED_B_ID = 993103
RETIRED_ID = 993104
LINK_ONLY_ID = 993105

TRAINING_ID = 993201
HIDDEN_TRAINING_ID = 993202
LESSON_ID = 993301
INACTIVE_LESSON_ID = 993302
HIDDEN_LESSON_ID = 993303

SEARCH_CONFIG = {
    "vector_bucket": "kb-vectors",
    "vector_index": "articles",
    "vector_region": "us-east-1",
    "embedding_model": "amazon.titan-embed-text-v2:0",
    "embedding_region": "sa-east-1",
}

# (id, paths, link, title, description, content, related, lessons, active)
_ARTICLES = (
    (
        ARTICLE_ID,
        ["Prescrição"],
        None,
        "ZZTest Avaliar prescrição",
        "Como avaliar uma prescrição",
        "<h2>Passo 1</h2><p>Abra a prescrição.</p>",
        [RELATED_B_ID, RETIRED_ID, ARTICLE_ID, RELATED_A_ID],
        [HIDDEN_LESSON_ID, LESSON_ID, INACTIVE_LESSON_ID],
        True,
    ),
    (
        RELATED_A_ID,
        ["Prescrição"],
        None,
        "ZZTest Checagem",
        None,
        "<p>Checagem</p>",
        None,
        None,
        True,
    ),
    (
        RELATED_B_ID,
        ["Relatórios"],
        None,
        "ZZTest Relatório",
        "Emitir relatório",
        "<p>Relatório</p>",
        None,
        None,
        True,
    ),
    (
        RETIRED_ID,
        ["Prescrição"],
        None,
        "ZZTest Aposentado",
        None,
        "<p>Antigo</p>",
        None,
        None,
        False,
    ),
    (
        LINK_ONLY_ID,
        ["Relatórios"],
        "https://kb.example.com/externo",
        "ZZTest Somente link",
        None,
        None,
        None,
        None,
        True,
    ),
)
_ARTICLE_IDS = [row[0] for row in _ARTICLES]


def _cleanup():
    session.execute(
        text(
            "DELETE FROM public.base_conhecimento WHERE idbase_conhecimento IN :ids"
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": _ARTICLE_IDS},
    )
    session.execute(
        text(
            "DELETE FROM public.treinamento_item "
            "WHERE idtreinamento_item BETWEEN 993300 AND 993399"
        )
    )
    session.execute(
        text(
            "DELETE FROM public.treinamento_esquema "
            "WHERE idtreinamento BETWEEN 993200 AND 993299"
        )
    )
    session.execute(
        text(
            "DELETE FROM public.treinamento WHERE idtreinamento BETWEEN 993200 AND 993299"
        )
    )
    session.execute(
        text("DELETE FROM public.memoria WHERE tipo = :kind"),
        {"kind": GlobalMemoryEnum.KB_SEARCH.value},
    )
    session_commit()


def _add_training(training_id, scope):
    session.execute(
        text(
            "INSERT INTO public.treinamento "
            "(idtreinamento, pagina, titulo, resumo, posicao, ativo, obrigatorio, "
            "escopo, audiencia, tempo_horas, created_at, created_by) "
            "VALUES (:id, ARRAY['kb-test'], :titulo, NULL, 1, true, false, :escopo, "
            "'all', 0, now(), :created_by)"
        ),
        {
            "id": training_id,
            "titulo": "ZZTest Módulo %d" % training_id,
            "escopo": scope,
            "created_by": DEMO_USER_ID,
        },
    )


def _add_lesson(item_id, training_id, active=True):
    session.execute(
        text(
            "INSERT INTO public.treinamento_item "
            "(idtreinamento_item, idtreinamento, titulo, posicao, ativo, "
            "created_at, created_by) "
            "VALUES (:id, :training_id, :titulo, 1, :ativo, now(), :created_by)"
        ),
        {
            "id": item_id,
            "training_id": training_id,
            "titulo": "ZZTest Aula %d" % item_id,
            "ativo": active,
            "created_by": DEMO_USER_ID,
        },
    )


@pytest.fixture(autouse=True)
def seed():
    """Articles, a module the demo schema sees and one only another schema sees."""
    _cleanup()

    for (
        id_kb,
        paths,
        link,
        title,
        description,
        content,
        related,
        lessons,
        active,
    ) in _ARTICLES:
        session.execute(
            text(
                "INSERT INTO public.base_conhecimento "
                "(idbase_conhecimento, pagina, link, titulo, resumo, conteudo, "
                "relacionados, aulas_relacionadas, ativo, created_at, created_by) "
                "VALUES (:id, :paths, :link, :title, :description, :content, "
                ":related, :lessons, :active, now(), :created_by)"
            ),
            {
                "id": id_kb,
                "paths": paths,
                "link": link,
                "title": title,
                "description": description,
                "content": content,
                "related": related,
                "lessons": lessons,
                "active": active,
                "created_by": DEMO_USER_ID,
            },
        )

    _add_training(TRAINING_ID, scope="global")
    _add_lesson(LESSON_ID, TRAINING_ID)
    _add_lesson(INACTIVE_LESSON_ID, TRAINING_ID, active=False)

    _add_training(HIDDEN_TRAINING_ID, scope="schemas")
    session.execute(
        text(
            "INSERT INTO public.treinamento_esquema "
            "(idtreinamento, schema_name, obrigatorio, created_at, created_by) "
            "VALUES (:id, :schema_name, false, now(), :created_by)"
        ),
        {
            "id": HIDDEN_TRAINING_ID,
            "schema_name": OTHER_SCHEMA,
            "created_by": DEMO_USER_ID,
        },
    )
    _add_lesson(HIDDEN_LESSON_ID, HIDDEN_TRAINING_ID)

    session.execute(
        text(
            "INSERT INTO public.memoria (tipo, valor, update_at, update_by) "
            "VALUES (:kind, CAST(:value AS json), now(), 1)"
        ),
        {"kind": GlobalMemoryEnum.KB_SEARCH.value, "value": json.dumps(SEARCH_CONFIG)},
    )
    session_commit()

    yield

    _cleanup()


@pytest.fixture
def search_mock():
    """Replace the vector search with a stub returning no hit by default."""
    with patch.object(
        knowledge_base_service.vector_search_service, "search", return_value=[]
    ) as mock:
        yield mock


def _chunk(distance, article_id, source_text="trecho"):
    return {
        "key": f"{article_id}-{distance}",
        "distance": distance,
        "metadata": {"article_id": article_id, "source_text": source_text},
    }


def _seeded(articles):
    return [a for a in articles if a["id"] in _ARTICLE_IDS]


# --- list ------------------------------------------------------------------


def test_list_requires_basic_features(client):
    """GET /knowledge-base/articles - 401 without a token"""
    response = client.get("/knowledge-base/articles")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_list_returns_published_articles_without_content(client, analyst_headers):
    """GET /knowledge-base/articles - active only, by title, no HTML payload"""
    response = client.get("/knowledge-base/articles", headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    articles = _seeded(response.get_json()["data"])

    assert [a["title"] for a in articles] == sorted(
        row[3] for row in _ARTICLES if row[8]
    )
    assert all("content" not in a for a in articles)

    by_id = {a["id"]: a for a in articles}
    assert by_id[ARTICLE_ID]["hasContent"] is True
    assert by_id[ARTICLE_ID]["path"] == ["Prescrição"]
    assert by_id[LINK_ONLY_ID]["hasContent"] is False
    assert by_id[LINK_ONLY_ID]["link"] == "https://kb.example.com/externo"


# --- article ---------------------------------------------------------------


def test_article_returns_content(client, analyst_headers):
    """GET /knowledge-base/articles/<id> - the HTML content is returned"""
    response = client.get(
        f"/knowledge-base/articles/{ARTICLE_ID}", headers=analyst_headers
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.get_json()["data"]
    assert data["id"] == ARTICLE_ID
    assert data["content"] == "<h2>Passo 1</h2><p>Abra a prescrição.</p>"


def test_article_related_keeps_order_and_drops_unpublished(client, analyst_headers):
    """GET /knowledge-base/articles/<id> - curated order, no retired article, no self"""
    response = client.get(
        f"/knowledge-base/articles/{ARTICLE_ID}", headers=analyst_headers
    )

    related = response.get_json()["data"]["related"]
    assert [r["id"] for r in related] == [RELATED_B_ID, RELATED_A_ID]
    assert related[0] == {
        "id": RELATED_B_ID,
        "title": "ZZTest Relatório",
        "description": "Emitir relatório",
    }


def test_article_related_lessons_only_visible_and_active(client, analyst_headers):
    """GET /knowledge-base/articles/<id> - lessons from modules the schema cannot
    see, and inactive lessons, are left out"""
    response = client.get(
        f"/knowledge-base/articles/{ARTICLE_ID}", headers=analyst_headers
    )

    assert response.get_json()["data"]["relatedLessons"] == [
        {
            "id": LESSON_ID,
            "trainingId": TRAINING_ID,
            "title": "ZZTest Aula %d" % LESSON_ID,
            "trainingTitle": "ZZTest Módulo %d" % TRAINING_ID,
        }
    ]


def test_article_without_relations(client, analyst_headers):
    """GET /knowledge-base/articles/<id> - NULL arrays yield empty lists"""
    response = client.get(
        f"/knowledge-base/articles/{RELATED_A_ID}", headers=analyst_headers
    )

    data = response.get_json()["data"]
    assert data["related"] == []
    assert data["relatedLessons"] == []


@pytest.mark.parametrize("id_article", [RETIRED_ID, 993999])
def test_article_not_found(client, analyst_headers, id_article):
    """GET /knowledge-base/articles/<id> - 404 for retired or unknown articles"""
    response = client.get(
        f"/knowledge-base/articles/{id_article}", headers=analyst_headers
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


# --- search ----------------------------------------------------------------


@pytest.mark.parametrize("payload", [{}, {"query": ""}, {"query": " ab "}])
def test_search_rejects_short_queries(client, analyst_headers, search_mock, payload):
    """POST /knowledge-base/search - 400 below the minimum length, no embedding cost"""
    response = client.post(
        "/knowledge-base/search", json=payload, headers=analyst_headers
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    search_mock.assert_not_called()


def test_search_requires_a_config(client, analyst_headers, search_mock):
    """POST /knowledge-base/search - clean 400 when the kb-search memory is missing"""
    session.execute(
        text("DELETE FROM public.memoria WHERE tipo = :kind"),
        {"kind": GlobalMemoryEnum.KB_SEARCH.value},
    )
    session_commit()

    response = client.post(
        "/knowledge-base/search", json={"query": "prescrição"}, headers=analyst_headers
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    search_mock.assert_not_called()


def test_search_uses_the_stored_config(client, analyst_headers, search_mock):
    """POST /knowledge-base/search - kb-search config, asking for many chunks"""
    client.post(
        "/knowledge-base/search",
        json={"query": "  avaliar prescrição "},
        headers=analyst_headers,
    )

    search_mock.assert_called_once()
    kwargs = search_mock.call_args.kwargs
    assert kwargs["query"] == "avaliar prescrição"
    assert kwargs["config"].vector_index == SEARCH_CONFIG["vector_index"]
    assert kwargs["config"].max_results == knowledge_base_service.SEARCH_CHUNKS


def test_search_collapses_chunks_and_drops_unpublished(
    client, analyst_headers, search_mock
):
    """POST /knowledge-base/search - one result per article, best chunk as the
    snippet, in distance order; retired, unknown and non-article hits dropped"""
    search_mock.return_value = [
        _chunk(0.1, str(RELATED_A_ID), "melhor trecho da checagem"),
        _chunk(0.2, str(RETIRED_ID)),
        _chunk(0.25, "993999"),
        {"key": "x", "distance": 0.3, "metadata": {}},
        _chunk(0.35, str(ARTICLE_ID), "trecho da prescrição"),
        _chunk(0.4, str(RELATED_A_ID), "outro trecho da checagem"),
    ]

    response = client.post(
        "/knowledge-base/search", json={"query": "checagem"}, headers=analyst_headers
    )

    assert response.status_code == status.HTTP_200_OK
    results = response.get_json()["data"]
    assert [r["id"] for r in results] == [RELATED_A_ID, ARTICLE_ID]
    assert results[0]["snippet"] == "melhor trecho da checagem"
    assert results[0]["score"] == 0.9
    assert results[0]["title"] == "ZZTest Checagem"


def test_search_truncates_long_snippets(client, analyst_headers, search_mock):
    """POST /knowledge-base/search - snippets are cut on a word boundary"""
    search_mock.return_value = [_chunk(0.1, str(ARTICLE_ID), "palavra " * 100)]

    response = client.post(
        "/knowledge-base/search", json={"query": "palavra"}, headers=analyst_headers
    )

    snippet = response.get_json()["data"][0]["snippet"]
    assert len(snippet) <= knowledge_base_service.SNIPPET_MAX_LENGTH + 1
    assert snippet.endswith("palavra…")


def test_search_drops_distant_matches(client, analyst_headers, search_mock):
    """POST /knowledge-base/search - an off-topic query returns nothing rather
    than the nearest (irrelevant) articles"""
    search_mock.return_value = [
        _chunk(0.5, str(ARTICLE_ID)),
        _chunk(0.88, str(RELATED_A_ID)),
    ]

    response = client.post(
        "/knowledge-base/search", json={"query": "bolo"}, headers=analyst_headers
    )

    assert [r["id"] for r in response.get_json()["data"]] == [ARTICLE_ID]
