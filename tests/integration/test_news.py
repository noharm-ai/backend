"""Tests: /news/* (novidades) and the recent news count sent at login

What matters here and is not obvious from the queries:
- only active news whose date has already come are published: a future date
  keeps a news record scheduled, on every endpoint and in the login count;
- the list is most recent first;
- the login count only covers the last RECENT_DAYS days.

Rows are seeded directly into the public table with high ids.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import bindparam, text

from services.news_service import RECENT_DAYS
from tests.conftest import session, session_commit
from utils import status

DEMO_USER_ID = 1

TODAY_ID = 994101
RECENT_ID = 994102
OLD_ID = 994103
INACTIVE_ID = 994104
SCHEDULED_ID = 994105
NO_CONTENT_ID = 994106

_TODAY = date.today()

# (id, date, title, description, content, active)
_NEWS = (
    (TODAY_ID, _TODAY, "ZZTest Hoje", "Resumo de hoje", "<p>Hoje</p>", True),
    (
        RECENT_ID,
        _TODAY - timedelta(days=RECENT_DAYS),
        "ZZTest Recente",
        None,
        "<p>Recente</p>",
        True,
    ),
    (
        OLD_ID,
        _TODAY - timedelta(days=RECENT_DAYS + 1),
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
def seed():
    """News on both sides of every publication rule."""
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


# --- list ------------------------------------------------------------------


def test_list_requires_auth(client):
    """GET /news - 401 without a token"""
    response = client.get("/news")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_list_returns_published_news_most_recent_first(client, analyst_headers):
    """GET /news - active and already dated only, newest first, no HTML payload"""
    response = client.get("/news", headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    news = _seeded(response.get_json()["data"])

    assert [n["id"] for n in news] == [TODAY_ID, RECENT_ID, OLD_ID, NO_CONTENT_ID]
    assert all("content" not in n for n in news)
    assert news[0] == {
        "id": TODAY_ID,
        "date": _TODAY.isoformat(),
        "title": "ZZTest Hoje",
        "description": "Resumo de hoje",
        "hasContent": True,
    }
    assert news[-1]["hasContent"] is False


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


def test_login_counts_recent_published_news(client):
    """POST /authenticate - recentNews counts the published news of the last
    RECENT_DAYS days: not the older, inactive or scheduled ones"""
    others = session.execute(
        text(
            "SELECT count(*) FROM public.novidade "
            "WHERE ativo AND data <= :today AND data >= :since "
            "AND idnovidade NOT IN :ids"
        ).bindparams(bindparam("ids", expanding=True)),
        {
            "today": _TODAY,
            "since": _TODAY - timedelta(days=RECENT_DAYS),
            "ids": _NEWS_IDS,
        },
    ).scalar()

    response = client.post(
        "/authenticate", json={"email": "demo", "password": "demo"}
    )

    assert response.status_code == status.HTTP_200_OK
    # TODAY_ID and RECENT_ID
    assert response.get_json()["recentNews"] == others + 2
