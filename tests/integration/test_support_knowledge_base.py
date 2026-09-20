"""Tests: POST /support/knowledge-base-articles

The support side panel shows the help articles that belong to the screen the
user is on. The endpoint backs that panel: it reads ``public.base_conhecimento``
and filters it by publication state (``active``) and by the screen paths an
article is pinned to (``path``, a text array column).

Both filters carry real consequences: ``active`` is what keeps a retired or
draft article out of the product, and ``path`` is an array *overlap* — an
article pinned to several screens must show up on each of them, and a request
naming several screens must get the union. Neither is obvious from the query,
so both are pinned down here, together with the alphabetical ordering the panel
relies on and the narrow payload (an article's internal id is never exposed).

Rows are seeded directly into the table: it is global (public schema), shared
by every client, and has no write endpoint of its own.
"""

import pytest
from sqlalchemy import bindparam, text

from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit
from utils import status

URL = "/support/knowledge-base-articles"

# High ids so the rows never collide with real content and are trivial to
# remove afterwards. Fields: (id, paths, link, title, description, active)
_PRESCRIPTION = (
    990101,
    ["/prescricao"],
    "https://kb.example.com/prescricao",
    "ZZTest Avaliar prescricao",
    "Como avaliar uma prescricao",
    True,
)
_SHARED = (
    990102,
    ["/prescricao", "/relatorios"],
    "https://kb.example.com/checagem",
    "ZZTest Checagem de itens",
    None,
    True,
)
_REPORTS = (
    990103,
    ["/relatorios"],
    "https://kb.example.com/relatorios",
    "ZZTest Emitir relatorio",
    "Como emitir um relatorio",
    True,
)
_RETIRED = (
    990104,
    ["/prescricao"],
    "https://kb.example.com/antigo",
    "ZZTest Artigo aposentado",
    "Conteudo desatualizado",
    False,
)

_ALL_ROWS = (_PRESCRIPTION, _SHARED, _REPORTS, _RETIRED)
_ALL_IDS = tuple(row[0] for row in _ALL_ROWS)


@pytest.fixture(autouse=True)
def seed_articles():
    """Insert the knowledge-base rows and remove them after the test."""
    for id_kb, paths, link, title, description, active in _ALL_ROWS:
        session.execute(
            text(
                "INSERT INTO public.base_conhecimento "
                "(idbase_conhecimento, pagina, link, titulo, resumo, ativo, "
                "created_at, created_by) "
                "VALUES (:id, :paths, :link, :title, :description, :active, now(), 1)"
            ),
            {
                "id": id_kb,
                "paths": paths,
                "link": link,
                "title": title,
                "description": description,
                "active": active,
            },
        )
    session_commit()

    yield

    session.execute(
        text(
            "DELETE FROM public.base_conhecimento WHERE idbase_conhecimento IN :ids"
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": list(_ALL_IDS)},
    )
    session_commit()


def _titles(response):
    """The titles of the returned articles, in the order they came back."""
    return [article["title"] for article in response.get_json()["data"]]


def test_knowledge_base_permission_denied(client):
    """POST /support/knowledge-base-articles - no READ_BASIC_FEATURES, no list [401]"""
    headers = make_headers(get_access(client, roles=[Role.DISPENSING_MANAGER.value]))

    response = client.post(URL, json={}, headers=headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_knowledge_base_without_filters_returns_every_article(client, analyst_headers):
    """POST /support/knowledge-base-articles - no filter lists every article"""
    response = client.post(URL, json={}, headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    assert set(_titles(response)) == {row[3] for row in _ALL_ROWS}


def test_knowledge_base_is_ordered_by_title(client, analyst_headers):
    """POST /support/knowledge-base-articles - articles come back alphabetically"""
    response = client.post(URL, json={}, headers=analyst_headers)

    titles = _titles(response)
    assert titles == sorted(titles)


def test_knowledge_base_active_filter_hides_retired_articles(client, analyst_headers):
    """POST /support/knowledge-base-articles - active=true omits retired articles"""
    response = client.post(URL, json={"active": True}, headers=analyst_headers)

    titles = _titles(response)
    assert _RETIRED[3] not in titles
    assert _PRESCRIPTION[3] in titles


def test_knowledge_base_inactive_filter_returns_only_retired(client, analyst_headers):
    """POST /support/knowledge-base-articles - active=false returns the retired ones"""
    response = client.post(URL, json={"active": False}, headers=analyst_headers)

    assert _titles(response) == [_RETIRED[3]]


def test_knowledge_base_path_filter_selects_the_screen(client, analyst_headers):
    """POST /support/knowledge-base-articles - path returns that screen's articles"""
    response = client.post(URL, json={"path": ["/relatorios"]}, headers=analyst_headers)

    assert set(_titles(response)) == {_REPORTS[3], _SHARED[3]}


def test_knowledge_base_path_filter_matches_any_of_the_screens(client, analyst_headers):
    """POST /support/knowledge-base-articles - an article pinned to several screens
    shows up on each of them"""
    prescription = client.post(
        URL, json={"path": ["/prescricao"]}, headers=analyst_headers
    )
    reports = client.post(URL, json={"path": ["/relatorios"]}, headers=analyst_headers)

    assert _SHARED[3] in _titles(prescription)
    assert _SHARED[3] in _titles(reports)


def test_knowledge_base_path_filter_is_an_overlap(client, analyst_headers):
    """POST /support/knowledge-base-articles - several paths return their union,
    each article only once"""
    response = client.post(
        URL, json={"path": ["/prescricao", "/relatorios"]}, headers=analyst_headers
    )

    titles = _titles(response)
    assert sorted(titles) == sorted(
        [_PRESCRIPTION[3], _SHARED[3], _REPORTS[3], _RETIRED[3]]
    )


def test_knowledge_base_unknown_path_returns_nothing(client, analyst_headers):
    """POST /support/knowledge-base-articles - a screen with no article lists none"""
    response = client.post(
        URL, json={"path": ["/tela-inexistente"]}, headers=analyst_headers
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == []


def test_knowledge_base_combines_both_filters(client, analyst_headers):
    """POST /support/knowledge-base-articles - active and path apply together"""
    response = client.post(
        URL, json={"active": True, "path": ["/prescricao"]}, headers=analyst_headers
    )

    assert set(_titles(response)) == {_PRESCRIPTION[3], _SHARED[3]}


def test_knowledge_base_exposes_only_the_panel_fields(client, analyst_headers):
    """POST /support/knowledge-base-articles - only link, title and description"""
    response = client.post(
        URL, json={"path": ["/relatorios"], "active": True}, headers=analyst_headers
    )

    articles = {item["title"]: item for item in response.get_json()["data"]}
    assert set(articles[_REPORTS[3]].keys()) == {"link", "title", "description"}
    assert articles[_REPORTS[3]]["link"] == _REPORTS[2]
    assert articles[_REPORTS[3]]["description"] == _REPORTS[4]


def test_knowledge_base_article_without_a_description(client, analyst_headers):
    """POST /support/knowledge-base-articles - a missing summary comes back as null"""
    response = client.post(URL, json={"active": True}, headers=analyst_headers)

    articles = {item["title"]: item for item in response.get_json()["data"]}
    assert articles[_SHARED[3]]["description"] is None
