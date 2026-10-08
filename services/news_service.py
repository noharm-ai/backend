"""Service: news (novidades)"""

from datetime import date

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import News
from repository import news_repository
from utils import status

# news per page of the list
PAGE_SIZE = 5
MAX_PAGE_SIZE = 20


def _summary(news: News) -> dict:
    return {
        "id": news.id,
        "date": news.date.isoformat(),
        "title": news.title,
        "description": news.description,
        "hasContent": bool(news.content),
    }


@has_permission(Permission.READ_BASIC_FEATURES)
def list_news(limit: int = PAGE_SIZE, offset: int = 0):
    """A page of the published news, most recent first, with their content"""
    if limit < 1 or offset < 0:
        raise ValidationError(
            "Paginação inválida",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    limit = min(limit, MAX_PAGE_SIZE)
    # one extra row tells whether there is a next page
    news = news_repository.list_published(
        today=date.today(), limit=limit + 1, offset=offset
    )

    return {
        "news": [{**_summary(n), "content": n.content} for n in news[:limit]],
        "hasMore": len(news) > limit,
    }


@has_permission(Permission.READ_BASIC_FEATURES)
def get_news(id_news: int):
    """A published news record with its content"""
    news = news_repository.get_published(id_news=id_news, today=date.today())

    if news is None:
        raise ValidationError(
            "Novidade não encontrada",
            "errors.invalidRecord",
            status.HTTP_404_NOT_FOUND,
        )

    return {**_summary(news), "content": news.content}


def count_recent_news() -> int:
    """Published news dated today (sent at login, lights up the menu badge)"""
    return news_repository.count_published_on(day=date.today())
