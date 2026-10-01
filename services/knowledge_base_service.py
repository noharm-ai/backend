"""Service: knowledge base (help center articles)"""

from datetime import datetime

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import GlobalMemory, KnowledgeBase, KnowledgeBaseElement
from models.enums import GlobalMemoryEnum
from models.main import User, db
from models.requests.knowledge_base_request import (
    KnowledgeBaseElementListRequest,
    KnowledgeBaseElementSaveRequest,
    KnowledgeBaseListRequest,
    KnowledgeBaseSearchRequest,
)
from repository import knowledge_base_repository, training_repository
from services import vector_search_service
from utils import status

SEARCH_MIN_LENGTH = 3
SEARCH_MAX_LENGTH = 500
# articles are indexed in chunks, so several hits can belong to one article:
# ask for far more chunks than the articles returned
SEARCH_CHUNKS = 60
SEARCH_MAX_ARTICLES = 12
# cosine distance past which a chunk is noise: off-topic queries land around
# 0.88 on the real index, while genuine matches stay below 0.8
SEARCH_MAX_DISTANCE = 0.8
SNIPPET_MAX_LENGTH = 280
# page of the elements shown on every screen (header, menu, drawers)
GLOBAL_PAGE = "*"


def _updated_at(kb: KnowledgeBase):
    date = kb.updated_at or kb.created_at

    return date.isoformat() if date else None


def _summary(kb: KnowledgeBase) -> dict:
    return {
        "id": kb.id,
        "title": kb.title,
        "description": kb.description,
        "path": kb.path or [],
        "link": kb.link,
        "hasContent": bool(kb.content),
        "updatedAt": _updated_at(kb),
    }


def _snippet(text: str) -> str:
    text = " ".join((text or "").split())

    if len(text) <= SNIPPET_MAX_LENGTH:
        return text

    return text[:SNIPPET_MAX_LENGTH].rsplit(" ", 1)[0] + "…"


def _search_config() -> vector_search_service.SearchConfig:
    config_memory = (
        db.session.query(GlobalMemory)
        .filter(GlobalMemory.kind == GlobalMemoryEnum.KB_SEARCH.value)
        .first()
    )

    if config_memory is None:
        raise ValidationError(
            "Busca da base de conhecimento não configurada",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    config = vector_search_service.SearchConfig(**config_memory.value)
    config.max_results = SEARCH_CHUNKS

    return config


@has_permission(Permission.READ_BASIC_FEATURES)
def list_articles():
    """Every published article, without its content"""
    results = knowledge_base_repository.list_knowledge_base(
        request_data=KnowledgeBaseListRequest(active=True)
    )

    return [_summary(kb) for kb in results]


@has_permission(Permission.READ_BASIC_FEATURES)
def get_article(id_article: int, user_context: User):
    """A published article with its content, related articles and lessons"""
    kb = knowledge_base_repository.get_active_article(id_article=id_article)

    if kb is None:
        raise ValidationError(
            "Artigo não encontrado",
            "errors.invalidRecord",
            status.HTTP_404_NOT_FOUND,
        )

    related_ids = [i for i in (kb.related or []) if i != kb.id]
    related_map = {
        r.id: r
        for r in knowledge_base_repository.list_active_articles_by_id(ids=related_ids)
    }

    lesson_ids = kb.related_lessons or []
    lesson_map = {
        item.id: (item, training)
        for item, training in training_repository.list_visible_lessons_by_id(
            training_item_ids=lesson_ids, schema=user_context.schema
        )
    }

    return {
        **_summary(kb),
        "content": kb.content,
        # keep the order curated in the arrays, dropping whatever is not
        # published (or, for lessons, not visible to the schema)
        "related": [
            {
                "id": related_map[i].id,
                "title": related_map[i].title,
                "description": related_map[i].description,
            }
            for i in dict.fromkeys(related_ids)
            if i in related_map
        ],
        "relatedLessons": [
            {
                "id": lesson_map[i][0].id,
                "trainingId": lesson_map[i][1].id,
                "title": lesson_map[i][0].title,
                "trainingTitle": lesson_map[i][1].title,
            }
            for i in dict.fromkeys(lesson_ids)
            if i in lesson_map
        ],
    }


@has_permission(Permission.READ_BASIC_FEATURES)
def search_articles(request_data: KnowledgeBaseSearchRequest):
    """Semantic search over the published articles, best match first"""
    query = (request_data.query or "").strip()

    if len(query) < SEARCH_MIN_LENGTH or len(query) > SEARCH_MAX_LENGTH:
        raise ValidationError(
            "Busca inválida",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    vectors = vector_search_service.search(query=query, config=_search_config())

    # vectors come sorted by distance: the first chunk of an article is its best
    best_chunks = {}
    for v in vectors:
        if v.get("distance", 1) > SEARCH_MAX_DISTANCE:
            break

        metadata = v.get("metadata") or {}
        try:
            article_id = int(metadata.get("article_id"))
        except (TypeError, ValueError):
            continue

        if article_id not in best_chunks:
            best_chunks[article_id] = v

    articles = {
        kb.id: kb
        for kb in knowledge_base_repository.list_active_articles_by_id(
            ids=list(best_chunks.keys())
        )
    }

    results = []
    for article_id, chunk in best_chunks.items():
        if article_id not in articles:
            continue

        results.append(
            {
                **_summary(articles[article_id]),
                "snippet": _snippet(chunk.get("metadata", {}).get("source_text")),
                "score": round(1 - chunk.get("distance", 1), 4),
            }
        )

    return results[:SEARCH_MAX_ARTICLES]


def _element_page(page: str) -> str:
    page = page.strip()

    if page != GLOBAL_PAGE and not page.startswith("/"):
        raise ValidationError(
            "Página inválida",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    return page


def _group_elements(
    rows: list[tuple[KnowledgeBaseElement, KnowledgeBase]],
) -> list[dict]:
    """One entry per element, its articles in the order the rows come"""
    elements = {}
    for element, kb in rows:
        key = (element.page, element.selector)

        if key not in elements:
            elements[key] = {
                "page": element.page,
                "selector": element.selector,
                "label": element.label,
                "articles": [],
            }

        # every row of an element carries the same label, but a missing one
        # should not hide it
        if not elements[key]["label"]:
            elements[key]["label"] = element.label

        elements[key]["articles"].append(
            {"id": kb.id, "title": kb.title, "description": kb.description}
        )

    return list(elements.values())


@has_permission(Permission.READ_BASIC_FEATURES)
def list_elements(request_data: KnowledgeBaseElementListRequest):
    """Elements of a screen (and of every screen) with published articles"""
    page = _element_page(request_data.page)
    pages = list(dict.fromkeys([page, GLOBAL_PAGE]))

    return _group_elements(knowledge_base_repository.list_elements(pages=pages))


@has_permission(Permission.WRITE_HELP_TEXT)
def save_element(request_data: KnowledgeBaseElementSaveRequest, user_context: User):
    """Set the published articles pinned to an element: none unpins it

    Rows pointing at unpublished articles are kept: the curator cannot see
    them, so leaving them out of the list is not a request to remove them.
    """
    page = _element_page(request_data.page)
    selector = request_data.selector.strip()
    label = (request_data.label or "").strip() or None
    article_ids = list(dict.fromkeys(request_data.articleIds))

    if not selector:
        raise ValidationError(
            "Elemento inválido",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    articles = knowledge_base_repository.list_active_articles_by_id(ids=article_ids)
    if len(articles) != len(article_ids):
        raise ValidationError(
            "Artigo não encontrado",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    rows = knowledge_base_repository.list_element_rows(page=page, selector=selector)
    published_ids = {
        kb.id
        for kb in knowledge_base_repository.list_active_articles_by_id(
            ids=[row.id_article for row in rows]
        )
    }

    pinned_ids = set()
    for row in rows:
        if row.id_article in published_ids and row.id_article not in article_ids:
            db.session.delete(row)
            continue

        row.label = label
        pinned_ids.add(row.id_article)

    now = datetime.today()
    for id_article in article_ids:
        if id_article in pinned_ids:
            continue

        db.session.add(
            KnowledgeBaseElement(
                id_article=id_article,
                page=page,
                selector=selector,
                label=label,
                created_at=now,
                created_by=user_context.id,
            )
        )

    db.session.flush()

    elements = _group_elements(
        knowledge_base_repository.list_elements(pages=[page], selector=selector)
    )

    return elements[0] if elements else None
