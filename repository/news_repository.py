"""Repository: news (novidades) related operations"""

from datetime import date, timedelta

from models.appendix import News
from models.main import db


def _published_query(today: date):
    """Active news whose date has already come"""
    return (
        db.session.query(News)
        .filter(News.active == True)
        .filter(News.date <= today)
    )


def list_published(today: date) -> list[News]:
    """Published news, most recent first"""
    return (
        _published_query(today=today)
        .order_by(News.date.desc(), News.id.desc())
        .all()
    )


def get_published(id_news: int, today: date) -> News | None:
    """A published news record"""
    return _published_query(today=today).filter(News.id == id_news).first()


def count_recent(today: date, days: int) -> int:
    """Published news dated within the last ``days`` days"""
    return (
        _published_query(today=today)
        .filter(News.date >= today - timedelta(days=days))
        .count()
    )
