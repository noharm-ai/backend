from datetime import datetime

from models.main import db, User
from models.appendix import KnowledgeBase
from models.requests.knowledge_base_request import (
    KnowledgeBaseListRequest,
    KnowledgeBaseUpsertRequest,
)
from repository import knowledge_base_repository
from decorators.has_permission_decorator import has_permission, Permission
from exception.validation_error import ValidationError
from utils import dateutils, status


@has_permission(Permission.ADMIN_KNOWLEDGE_BASE)
def get_knowledge_base(request_data: KnowledgeBaseListRequest):
    results = knowledge_base_repository.list_knowledge_base(request_data=request_data)

    return [_to_dto(item) for item in results]


@has_permission(Permission.ADMIN_KNOWLEDGE_BASE)
def upsert_knowledge_base(
    request_data: KnowledgeBaseUpsertRequest, user_context: User
):
    if request_data.id:
        kb = knowledge_base_repository.get_by_id(request_data.id)
        if not kb:
            raise ValidationError(
                "Registro não encontrado",
                "errors.notFound",
                status.HTTP_404_NOT_FOUND,
            )
    else:
        kb = KnowledgeBase()
        kb.created_at = datetime.today()
        kb.created_by = user_context.id
        db.session.add(kb)

    kb.path = request_data.path
    kb.link = request_data.link
    kb.title = request_data.title
    kb.description = request_data.description
    kb.active = request_data.active
    kb.updated_at = datetime.today()
    kb.updated_by = user_context.id

    db.session.flush()

    return _to_dto(kb)


def _to_dto(kb: KnowledgeBase):
    return {
        "id": kb.id,
        "path": kb.path,
        "link": kb.link,
        "title": kb.title,
        "description": kb.description,
        "active": kb.active,
        "createdAt": dateutils.to_iso(kb.created_at),
        "updatedAt": dateutils.to_iso(kb.updated_at),
    }
