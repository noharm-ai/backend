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

``public.base_conhecimento`` is global, shared by every client: every row these
tests write has a title starting with ``ZZTest KB`` and is removed on the way in
and on the way out.
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
