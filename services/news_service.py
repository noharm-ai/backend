"""Service: news (novidades)"""

from datetime import date

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import News
from repository import news_repository
from utils import status

# news dated within these last days light up the menu badge
RECENT_DAYS = 3


def _summary(news: News) -> dict:
    return {
        "id": news.id,
        "date": news.date.isoformat(),
        "title": news.title,
        "description": news.description,
        "hasContent": bool(news.content),
    }


@has_permission(Permission.READ_BASIC_FEATURES)
def list_news():
    """Published news, most recent first, without content"""
    return [
        _summary(n) for n in news_repository.list_published(today=date.today())
    ]


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
    """Published news from the last RECENT_DAYS days (sent at login)"""
    return news_repository.count_recent(today=date.today(), days=RECENT_DAYS)
