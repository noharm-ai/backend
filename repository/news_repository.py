"""Repository: news (novidades) related operations"""

from datetime import date

from models.appendix import News
from models.main import db


def _published_query(today: date):
    """Active news whose date has already come"""
    return db.session.query(News).filter(News.active == True).filter(News.date <= today)


def list_published(today: date, limit: int, offset: int) -> list[News]:
    """A page of the published news, most recent first (the id breaks ties,
    so pages never overlap)"""
    return (
        _published_query(today=today)
        .order_by(News.date.desc(), News.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_published(id_news: int, today: date) -> News | None:
    """A published news record"""
    return _published_query(today=today).filter(News.id == id_news).first()


def count_published_on(day: date) -> int:
    """Published news dated on ``day``"""
    return _published_query(today=day).filter(News.date == day).count()
