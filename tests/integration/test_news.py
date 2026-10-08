"""Tests: /news/* (novidades) and the recent news count sent at login

What matters here and is not obvious from the queries:
- only active news whose date has already come are published: a future date
  keeps a news record scheduled, on every endpoint and in the login count;
- the list is most recent first, paginated by limit/offset with a hasMore
  flag; pages never overlap;
- the login count only covers the news dated today.

Rows are seeded directly into the public table with high ids.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import bindparam, text

from services import news_service
from services.news_service import PAGE_SIZE
from tests.conftest import session, session_commit
from utils import status

DEMO_USER_ID = 1

TODAY_ID = 994101
YESTERDAY_ID = 994102
OLD_ID = 994103
INACTIVE_ID = 994104
SCHEDULED_ID = 994105
NO_CONTENT_ID = 994106

_TODAY = date.today()


class _FixedDate(date):
    """date whose today() is _TODAY: the service and the seed must agree on
    the day, and the process clock may switch from UTC to America/Sao_Paulo
    mid-run (the dates differ every evening from 21:00 to midnight)"""

    @classmethod
    def today(cls):
        return _TODAY


# (id, date, title, description, content, active)
_NEWS = (
    (TODAY_ID, _TODAY, "ZZTest Hoje", "Resumo de hoje", "<p>Hoje</p>", True),
    (
        YESTERDAY_ID,
        _TODAY - timedelta(days=1),
        "ZZTest Ontem",
        None,
        "<p>Ontem</p>",
        True,
    ),
    (
        OLD_ID,
        _TODAY - timedelta(days=10),
        "ZZTest Antiga",
        None,
        "<p>Antiga</p>",
        True,
    ),
    (INACTIVE_ID, _TODAY, "ZZTest Inativa", None, "<p>Rascunho</p>", False),
    (
        SCHEDULED_ID,
        _TODAY + timedelta(days=1),
        "ZZTest Agendada",
        None,
        "<p>Amanhã</p>",
        True,
    ),
    (
        NO_CONTENT_ID,
        _TODAY - timedelta(days=30),
        "ZZTest Sem conteúdo",
        "Só o resumo",
        None,
        True,
    ),
)
_NEWS_IDS = [row[0] for row in _NEWS]


def _cleanup():
    session.execute(
        text("DELETE FROM public.novidade WHERE idnovidade IN :ids").bindparams(
            bindparam("ids", expanding=True)
        ),
        {"ids": _NEWS_IDS},
    )
    session_commit()


@pytest.fixture(autouse=True)
def seed(monkeypatch):
    """News on both sides of every publication rule."""
    monkeypatch.setattr(news_service, "date", _FixedDate)
    _cleanup()

    for id_news, news_date, title, description, content, active in _NEWS:
        session.execute(
            text(
                "INSERT INTO public.novidade "
                "(idnovidade, data, titulo, resumo, conteudo, ativo, "
                "created_at, created_by) "
                "VALUES (:id, :date, :title, :description, :content, :active, "
                "now(), :created_by)"
            ),
            {
                "id": id_news,
                "date": news_date,
                "title": title,
                "description": description,
                "content": content,
                "active": active,
                "created_by": DEMO_USER_ID,
            },
        )
    session_commit()

    yield

    _cleanup()


def _seeded(news):
    return [n for n in news if n["id"] in _NEWS_IDS]


def _all_pages(client, headers, limit):
    """Every page of the list, in order"""
    pages, offset = [], 0
    while True:
        response = client.get(f"/news?limit={limit}&offset={offset}", headers=headers)
        assert response.status_code == status.HTTP_200_OK
        page = response.get_json()["data"]
        pages.append(page)
        if not page["hasMore"]:
            return pages
        offset += limit


# --- list ------------------------------------------------------------------


def test_list_requires_auth(client):
    """GET /news - 401 without a token"""
    response = client.get("/news")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_list_returns_published_news_most_recent_first(client, analyst_headers):
    """GET /news - active and already dated only, newest first, with content"""
    news = _seeded(
        [n for page in _all_pages(client, analyst_headers, 20) for n in page["news"]]
    )

    assert [n["id"] for n in news] == [TODAY_ID, YESTERDAY_ID, OLD_ID, NO_CONTENT_ID]
    assert news[0] == {
        "id": TODAY_ID,
        "date": _TODAY.isoformat(),
        "title": "ZZTest Hoje",
        "description": "Resumo de hoje",
        "hasContent": True,
        "content": "<p>Hoje</p>",
    }
    assert news[-1]["hasContent"] is False
    assert news[-1]["content"] is None


def test_list_is_paginated(client, analyst_headers):
    """GET /news - small pages chain into the full list, without overlap, and
    only the last one has no next page"""
    full = [
        n["id"]
        for page in _all_pages(client, analyst_headers, 20)
        for n in page["news"]
    ]
    pages = _all_pages(client, analyst_headers, 2)
    paged = [n["id"] for page in pages for n in page["news"]]

    assert paged == full
    assert len(set(paged)) == len(paged)
    assert all(len(page["news"]) == 2 for page in pages[:-1])
    assert all(page["hasMore"] for page in pages[:-1])
    assert pages[-1]["hasMore"] is False


def test_list_default_page_size(client, analyst_headers):
    """GET /news - without params, the first PAGE_SIZE news"""
    response = client.get("/news", headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    assert len(response.get_json()["data"]["news"]) <= PAGE_SIZE


def test_list_past_the_end_is_empty(client, analyst_headers):
    """GET /news - an offset past the last news is an empty last page"""
    response = client.get("/news?offset=100000", headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == {"news": [], "hasMore": False}


@pytest.mark.parametrize("query", ["limit=0", "limit=-1", "offset=-1"])
def test_list_invalid_pagination(client, analyst_headers, query):
    """GET /news - a non positive limit or a negative offset is a 400"""
    response = client.get(f"/news?{query}", headers=analyst_headers)

    assert response.status_code == status.HTTP_400_BAD_REQUEST


# --- detail ----------------------------------------------------------------


def test_get_requires_auth(client):
    """GET /news/<id> - 401 without a token"""
    response = client.get(f"/news/{TODAY_ID}")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_get_returns_content(client, analyst_headers):
    """GET /news/<id> - the HTML content is returned"""
    response = client.get(f"/news/{TODAY_ID}", headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    data = response.get_json()["data"]
    assert data["id"] == TODAY_ID
    assert data["content"] == "<p>Hoje</p>"


@pytest.mark.parametrize("id_news", [INACTIVE_ID, SCHEDULED_ID, 999999999])
def test_get_unpublished_is_not_found(client, analyst_headers, id_news):
    """GET /news/<id> - inactive, scheduled or missing news are a 404"""
    response = client.get(f"/news/{id_news}", headers=analyst_headers)

    assert response.status_code == status.HTTP_404_NOT_FOUND


# --- login -----------------------------------------------------------------


def test_login_counts_todays_published_news(client):
    """POST /authenticate - recentNews counts the published news dated today:
    not yesterday's or older, inactive or scheduled ones"""
    others = session.execute(
        text(
            "SELECT count(*) FROM public.novidade "
            "WHERE ativo AND data = :today "
            "AND idnovidade NOT IN :ids"
        ).bindparams(bindparam("ids", expanding=True)),
        {
            "today": _TODAY,
            "ids": _NEWS_IDS,
        },
    ).scalar()

    response = client.post("/authenticate", json={"email": "demo", "password": "demo"})

    assert response.status_code == status.HTTP_200_OK
    # TODAY_ID only
    assert response.get_json()["recentNews"] == others + 1
