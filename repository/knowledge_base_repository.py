"""Repository: knowledge base related operations"""

from models.appendix import KnowledgeBase
from models.main import db
from models.requests.knowledge_base_request import KnowledgeBaseListRequest


def list_knowledge_base(request_data: KnowledgeBaseListRequest) -> list[KnowledgeBase]:
    """List knowledge base records"""
    query = db.session.query(KnowledgeBase)

    if request_data.active is not None:
        query = query.filter(KnowledgeBase.active == request_data.active)

    if request_data.path:
        query = query.filter(KnowledgeBase.path.overlap(request_data.path))

    return query.order_by(KnowledgeBase.title).all()


def get_active_article(id_article: int) -> KnowledgeBase | None:
    """Get a published knowledge base article"""
    return (
        db.session.query(KnowledgeBase)
        .filter(KnowledgeBase.id == id_article)
        .filter(KnowledgeBase.active == True)
        .first()
    )


def list_active_articles_by_id(ids: list[int]) -> list[KnowledgeBase]:
    """Published knowledge base articles among the given ids, in no given order"""
    if not ids:
        return []

    return (
        db.session.query(KnowledgeBase)
        .filter(KnowledgeBase.id.in_(ids))
        .filter(KnowledgeBase.active == True)
        .all()
    )
