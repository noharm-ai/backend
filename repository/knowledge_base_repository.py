"""Repository: knowledge base related operations"""

from models.main import db
from models.appendix import KnowledgeBase
from models.requests.knowledge_base_request import KnowledgeBaseListRequest


def list_knowledge_base(request_data: KnowledgeBaseListRequest) -> list[KnowledgeBase]:
    """List knowledge base records"""
    query = db.session.query(KnowledgeBase)

    if request_data.active is not None:
        query = query.filter(KnowledgeBase.active == request_data.active)

    if request_data.path:
        query = query.filter(KnowledgeBase.path.overlap(request_data.path))

    return query.order_by(KnowledgeBase.path, KnowledgeBase.title).all()


def get_by_id(id: int) -> KnowledgeBase:
    """Fetch a single knowledge base record by id"""
    return db.session.query(KnowledgeBase).filter(KnowledgeBase.id == id).first()
