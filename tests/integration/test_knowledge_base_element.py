"""Tests: /knowledge-base/elements (articles pinned to screen elements)

In help mode the app highlights the elements of the current screen that have
knowledge base articles pinned to them; curators (WRITE_HELP_TEXT) pin them.

What matters here and is not obvious from the queries:
- ``pagina`` is a route pattern, or ``*`` for the elements on every screen
  (header, menu, drawers), so a screen also gets the global elements;
- an element with several articles is several rows, grouped back into one
  element with one label;
- ``ativo`` keeps a draft or retired article out of help mode, and a save
  leaves its rows alone: the curator never sees them, so leaving them out of
  the list is not a request to unpin them;
- a save sends the element's complete article set, so an empty set unpins it.

Rows are seeded directly into the public tables with high ids.
"""

import pytest
from sqlalchemy import bindparam, text

from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit

DEMO_USER_ID = 1
CURATOR_USER_ID = 3

PAGE = "/zztest/:slug"
OTHER_PAGE = "/zztest-outra"
GLOBAL_PAGE = "*"

TABLE_SELECTOR = '[data-kb="zztest.table"]'
HEADER_SELECTOR = '[data-kb="zztest.header"]'
RETIRED_SELECTOR = '[data-kb="zztest.retired"]'
OTHER_SELECTOR = '[data-kb="zztest.other"]'
NEW_SELECTOR = '[data-kb="zztest.new"]'

ARTICLE_B_ID = 993401
ARTICLE_A_ID = 993402
ARTICLE_C_ID = 993403
RETIRED_ID = 993404

# (id, title, active)
_ARTICLES = (
    (ARTICLE_B_ID, "ZZTest B Checagem", True),
    (ARTICLE_A_ID, "ZZTest A Avaliação", True),
    (ARTICLE_C_ID, "ZZTest C Relatório", True),
    (RETIRED_ID, "ZZTest Aposentado", False),
)
_ARTICLE_IDS = [row[0] for row in _ARTICLES]

# (page, selector, article, label)
_ELEMENTS = (
    (PAGE, TABLE_SELECTOR, ARTICLE_B_ID, "Tabela"),
    (PAGE, TABLE_SELECTOR, ARTICLE_A_ID, "Tabela"),
    (PAGE, TABLE_SELECTOR, RETIRED_ID, "Tabela"),
    (PAGE, RETIRED_SELECTOR, RETIRED_ID, "Só aposentado"),
    (GLOBAL_PAGE, HEADER_SELECTOR, ARTICLE_C_ID, None),
    (OTHER_PAGE, OTHER_SELECTOR, ARTICLE_A_ID, "Outra tela"),
)


def _cleanup():
    # pinned elements go along with their articles (ON DELETE CASCADE)
    session.execute(
        text(
            "DELETE FROM public.base_conhecimento WHERE idbase_conhecimento IN :ids"
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": _ARTICLE_IDS},
    )
    session_commit()


def _rows(page, selector):
    """(article, label, created_by) of an element, by article id"""
    return session.execute(
        text(
            "SELECT idbase_conhecimento, rotulo, created_by "
            "FROM public.base_conhecimento_elemento "
            "WHERE pagina = :page AND seletor = :selector "
            "ORDER BY idbase_conhecimento"
        ),
        {"page": page, "selector": selector},
    ).all()


def _ours(elements):
    """Only the elements seeded here: the table is shared by every schema"""
    return [e for e in elements if "zztest" in e["selector"]]


@pytest.fixture(autouse=True)
def seed():
    _cleanup()

    for id_kb, title, active in _ARTICLES:
        session.execute(
            text(
                "INSERT INTO public.base_conhecimento "
                "(idbase_conhecimento, pagina, titulo, resumo, conteudo, ativo, "
                "created_at, created_by) "
                "VALUES (:id, ARRAY['Prescrição'], :title, :description, "
                "'<p>conteúdo</p>', :active, now(), :created_by)"
            ),
            {
                "id": id_kb,
                "title": title,
                "description": "Resumo %d" % id_kb,
                "active": active,
                "created_by": DEMO_USER_ID,
            },
        )

    for page, selector, id_kb, label in _ELEMENTS:
        session.execute(
            text(
                "INSERT INTO public.base_conhecimento_elemento "
                "(idbase_conhecimento, pagina, seletor, rotulo, created_at, "
                "created_by) "
                "VALUES (:id_kb, :page, :selector, :label, now(), :created_by)"
            ),
            {
                "id_kb": id_kb,
                "page": page,
                "selector": selector,
                "label": label,
                "created_by": DEMO_USER_ID,
            },
        )
    session_commit()

    yield

    _cleanup()


def _list(client, headers, page=PAGE):
    return client.get(
        "/knowledge-base/elements", query_string={"page": page}, headers=headers
    )


def _save(client, headers, **body):
    payload = {"page": PAGE, "selector": NEW_SELECTOR, "label": None, "articleIds": []}
    payload.update(body)

    return client.put("/knowledge-base/elements", json=payload, headers=headers)


# --- list ---------------------------------------------------------------------


def test_list_elements_of_page_and_global(client, analyst_headers):
    """A screen gets its own elements and the global ones, grouped, articles
    by title and retired ones left out [200 OK]."""
    response = _list(client, analyst_headers)

    assert response.status_code == 200
    elements = _ours(response.get_json()["data"])

    assert elements == [
        {
            "page": GLOBAL_PAGE,
            "selector": HEADER_SELECTOR,
            "label": None,
            "articles": [
                {
                    "id": ARTICLE_C_ID,
                    "title": "ZZTest C Relatório",
                    "description": "Resumo %d" % ARTICLE_C_ID,
                }
            ],
        },
        {
            "page": PAGE,
            "selector": TABLE_SELECTOR,
            "label": "Tabela",
            "articles": [
                {
                    "id": ARTICLE_A_ID,
                    "title": "ZZTest A Avaliação",
                    "description": "Resumo %d" % ARTICLE_A_ID,
                },
                {
                    "id": ARTICLE_B_ID,
                    "title": "ZZTest B Checagem",
                    "description": "Resumo %d" % ARTICLE_B_ID,
                },
            ],
        },
    ]


def test_list_global_page_only_global(client, analyst_headers):
    """Asking for the global page returns only the global elements [200 OK]."""
    response = _list(client, analyst_headers, page=GLOBAL_PAGE)

    assert response.status_code == 200
    assert [e["selector"] for e in _ours(response.get_json()["data"])] == [
        HEADER_SELECTOR
    ]


def test_list_unknown_page_only_global(client, analyst_headers):
    """A screen with nothing pinned still gets the global elements [200 OK]."""
    response = _list(client, analyst_headers, page="/zztest-vazia")

    assert response.status_code == 200
    assert [e["selector"] for e in _ours(response.get_json()["data"])] == [
        HEADER_SELECTOR
    ]


@pytest.mark.parametrize("page", ["", "zztest", "prescricao/:slug"])
def test_list_invalid_page(client, analyst_headers, page):
    """The page is a route pattern or * [400 BAD REQUEST]."""
    response = _list(client, analyst_headers, page=page)

    assert response.status_code == 400


def test_list_permission_denied(client):
    """Without READ_BASIC_FEATURES the list is rejected [401 UNAUTHORIZED]."""
    headers = make_headers(get_access(client, roles=[Role.DISPENSING_MANAGER.value]))

    assert _list(client, headers).status_code == 401


# --- save ---------------------------------------------------------------------


def test_save_new_element(client, curator_headers):
    """A curator pins articles to a new element, deduplicated [200 OK]."""
    response = _save(
        client,
        curator_headers,
        label="  Novo elemento  ",
        articleIds=[ARTICLE_C_ID, ARTICLE_A_ID, ARTICLE_C_ID],
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["page"] == PAGE
    assert data["selector"] == NEW_SELECTOR
    assert data["label"] == "Novo elemento"
    assert [a["id"] for a in data["articles"]] == [ARTICLE_A_ID, ARTICLE_C_ID]

    assert _rows(PAGE, NEW_SELECTOR) == [
        (ARTICLE_A_ID, "Novo elemento", CURATOR_USER_ID),
        (ARTICLE_C_ID, "Novo elemento", CURATOR_USER_ID),
    ]


def test_save_global_element(client, admin_headers):
    """An admin pins an article to every screen [200 OK]."""
    response = _save(client, admin_headers, page=GLOBAL_PAGE, articleIds=[ARTICLE_B_ID])

    assert response.status_code == 200
    assert response.get_json()["data"]["page"] == GLOBAL_PAGE
    assert [row[0] for row in _rows(GLOBAL_PAGE, NEW_SELECTOR)] == [ARTICLE_B_ID]


def test_save_replaces_article_set(client, curator_headers):
    """Saving swaps the articles and relabels the kept rows; the retired
    article's row stays, relabeled with the rest [200 OK]."""
    response = _save(
        client,
        curator_headers,
        selector=TABLE_SELECTOR,
        label="Lista de medicamentos",
        articleIds=[ARTICLE_B_ID, ARTICLE_C_ID],
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["label"] == "Lista de medicamentos"
    assert [a["id"] for a in data["articles"]] == [ARTICLE_B_ID, ARTICLE_C_ID]

    assert _rows(PAGE, TABLE_SELECTOR) == [
        (ARTICLE_B_ID, "Lista de medicamentos", DEMO_USER_ID),
        (ARTICLE_C_ID, "Lista de medicamentos", CURATOR_USER_ID),
        (RETIRED_ID, "Lista de medicamentos", DEMO_USER_ID),
    ]


def test_save_empty_set_unpins(client, curator_headers):
    """An empty article set unpins the element: it leaves help mode, only the
    retired article's row is left [200 OK]."""
    response = _save(client, curator_headers, selector=TABLE_SELECTOR, articleIds=[])

    assert response.status_code == 200
    assert response.get_json()["data"] is None
    assert [row[0] for row in _rows(PAGE, TABLE_SELECTOR)] == [RETIRED_ID]

    listed = _ours(_list(client, curator_headers).get_json()["data"])
    assert TABLE_SELECTOR not in [e["selector"] for e in listed]


def test_save_same_selector_other_page(client, curator_headers):
    """An element is a page and a selector: the same selector on another
    screen is a separate element [200 OK]."""
    response = _save(
        client,
        curator_headers,
        page=OTHER_PAGE,
        selector=TABLE_SELECTOR,
        articleIds=[ARTICLE_C_ID],
    )

    assert response.status_code == 200
    assert [row[0] for row in _rows(OTHER_PAGE, TABLE_SELECTOR)] == [ARTICLE_C_ID]
    assert [row[0] for row in _rows(PAGE, TABLE_SELECTOR)] == [
        ARTICLE_B_ID,
        ARTICLE_A_ID,
        RETIRED_ID,
    ]


@pytest.mark.parametrize("article_id", [RETIRED_ID, 993499])
def test_save_unpublished_article(client, curator_headers, article_id):
    """Only published articles can be pinned, and nothing is written
    [400 BAD REQUEST]."""
    response = _save(client, curator_headers, articleIds=[ARTICLE_A_ID, article_id])

    assert response.status_code == 400
    assert _rows(PAGE, NEW_SELECTOR) == []


@pytest.mark.parametrize(
    "body",
    [
        {"page": "zztest"},
        {"page": ""},
        {"selector": "   "},
        {"selector": "x" * 1001},
        {"label": "x" * 256},
        {"articleIds": list(range(1, 22))},
    ],
)
def test_save_invalid_params(client, curator_headers, body):
    """Page, selector, label and article set are validated [400 BAD REQUEST]."""
    response = _save(client, curator_headers, **{"articleIds": [ARTICLE_A_ID], **body})

    assert response.status_code == 400
    assert _rows(PAGE, NEW_SELECTOR) == []


def test_save_permission_denied(client, analyst_headers):
    """Without WRITE_HELP_TEXT the save is rejected and nothing is written
    [401 UNAUTHORIZED]."""
    response = _save(client, analyst_headers, articleIds=[ARTICLE_A_ID])

    assert response.status_code == 401
    assert _rows(PAGE, NEW_SELECTOR) == []
