"""Service: knowledge base articles (maintenance and reading)"""

from urllib.parse import urlparse

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import KnowledgeBase
from models.main import User
from models.requests.knowledge_base_request import (
    KnowledgeBaseManageListRequest,
    KnowledgeBaseUpsertRequest,
)
from repository import knowledge_base_repository, training_repository
from services import knowledge_base_vector_service
from services.knowledge_base_vector_service import ArticleDocument
from utils import dateutils, status


def _lesson_dict(lesson, training) -> dict:
    """A training lesson as the article references it"""
    return {
        "id": lesson.id,
        "title": lesson.title,
        "trainingId": training.id,
        "trainingTitle": training.title,
    }


def _lessons(kb: KnowledgeBase, schema: str | None) -> list[dict]:
    """The article lessons that still exist and are active; only those of the
    modules ``schema`` sees, unless schema is None (maintainers)"""
    return [
        _lesson_dict(lesson, training)
        for lesson, training in training_repository.list_lessons(
            ids=kb.training_items or [], schema=schema
        )
    ]


def _to_dict(
    kb: KnowledgeBase, with_content: bool, lessons: list[dict] | None = None
) -> dict:
    """Serialize an article; the body only goes out when asked for"""
    article = {
        "id": kb.id,
        "title": kb.title,
        "description": kb.description,
        "path": kb.path or [],
        "section": kb.section or [],
        "trainingItems": kb.training_items or [],
        "link": kb.link,
        "active": kb.active,
        "hasContent": bool(kb.content),
        "createdAt": dateutils.to_iso(kb.created_at),
        "updatedAt": dateutils.to_iso(kb.updated_at),
    }

    if with_content:
        article["content"] = kb.content
        article["trainingLessons"] = lessons or []

    return article


def _document(kb: KnowledgeBase, lessons: list[dict]) -> ArticleDocument:
    """What the vector index gets from the article"""
    return ArticleDocument(
        id=kb.id,
        title=kb.title,
        active=kb.active,
        description=kb.description,
        content=kb.content,
        lessons=[f"{item['trainingTitle']} › {item['title']}" for item in lessons],
    )


def _is_http_url(link: str) -> bool:
    """Whether the link is an absolute http(s) URL"""
    parsed = urlparse(link)

    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _not_found():
    """The error for an unknown (or hidden) article"""
    return ValidationError(
        "Artigo inexistente",
        "errors.invalidRecord",
        status.HTTP_400_BAD_REQUEST,
    )


@has_permission(Permission.WRITE_KNOWLEDGE_BASE)
def list_articles(request_data: KnowledgeBaseManageListRequest):
    """List every article (active or not) for the maintenance screen"""
    results = knowledge_base_repository.list_for_maintenance(request_data=request_data)

    return [_to_dict(kb, with_content=False) for kb in results]


@has_permission(Permission.READ_BASIC_FEATURES, Permission.WRITE_KNOWLEDGE_BASE)
def get_article(
    id_article: int, user_context: User, user_permissions: list[Permission]
):
    """Get an article with its content.

    Readers only see active articles; maintainers also see the inactive ones,
    which is how they review a draft before publishing it.
    """
    kb = knowledge_base_repository.get_by_id(id_article=id_article)

    if kb is None:
        raise _not_found()

    is_maintainer = Permission.WRITE_KNOWLEDGE_BASE in user_permissions

    if not kb.active and not is_maintainer:
        raise _not_found()

    # readers only get the lessons their schema has access to
    lessons = _lessons(kb, schema=None if is_maintainer else user_context.schema)

    return _to_dict(kb, with_content=True, lessons=lessons)


@has_permission(Permission.WRITE_KNOWLEDGE_BASE)
def upsert_article(request_data: KnowledgeBaseUpsertRequest, user_context: User):
    """Create or update an article"""
    if not request_data.title:
        raise ValidationError(
            "O título é obrigatório",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    if request_data.link and not _is_http_url(request_data.link):
        # the panel opens the link in a new tab: never a javascript: or data: URL
        raise ValidationError(
            "O link deve ser um endereço http(s)",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    if not request_data.content and not request_data.link:
        raise ValidationError(
            "O artigo precisa de um conteúdo ou de um link",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    if request_data.training_items:
        found = training_repository.list_lessons(ids=request_data.training_items)
        if len(found) != len(request_data.training_items):
            raise ValidationError(
                "Aula de treinamento inexistente ou inativa",
                "errors.invalidParams",
                status.HTTP_400_BAD_REQUEST,
            )

    record = None
    if request_data.id is not None:
        record = knowledge_base_repository.get_by_id(id_article=request_data.id)
        if record is None:
            raise _not_found()

    kb = knowledge_base_repository.upsert(
        request_data=request_data, record=record, user_id=user_context.id
    )

    lessons = _lessons(kb, schema=None)
    article = _to_dict(kb, with_content=True, lessons=lessons)
    # the article is saved even when the index is out of reach: the status
    # tells the maintainer to reindex it later
    article["vectorIndex"] = knowledge_base_vector_service.index_article(
        _document(kb, lessons)
    )

    return article


@has_permission(Permission.WRITE_KNOWLEDGE_BASE)
def reindex_article(id_article: int):
    """Write the article to the vector index again (or remove it, if inactive)"""
    kb = knowledge_base_repository.get_by_id(id_article=id_article)
    if kb is None:
        raise _not_found()

    status_index = knowledge_base_vector_service.index_article(
        _document(kb, _lessons(kb, schema=None))
    )

    return {"id": kb.id, "vectorIndex": status_index}


@has_permission(Permission.WRITE_KNOWLEDGE_BASE)
def list_training_lessons():
    """Every active lesson of the active training modules, for the article form"""
    return [
        _lesson_dict(lesson, training)
        for lesson, training in training_repository.list_lessons()
    ]
