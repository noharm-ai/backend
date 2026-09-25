"""Repository: knowledge base related operations"""

import re
from datetime import datetime

from sqlalchemy import or_, text

from models.appendix import KnowledgeBase
from models.main import db
from models.requests.knowledge_base_request import (
    KnowledgeBaseListRequest,
    KnowledgeBaseManageListRequest,
    KnowledgeBaseUpsertRequest,
)
from utils import stringutils

# postgres has no unaccent() without the extension: translate() folds the
# accents of portuguese text, so "prescrição" and "prescricao" match each other
_ACCENTED = "áàâãäéèêëíìîïóòôõöúùûüçñ"
_UNACCENTED = "aaaaaeeeeiiiiooooouuuucn"

# the searchable document of an article: the title weighs the most, then the
# summary, then the screens/sections it is pinned to and finally the body, with
# the HTML markup of the editor stripped
_SEARCH_SQL = text(
    """
    WITH artigos AS (
        SELECT
            idbase_conhecimento,
            setweight(to_tsvector('portuguese', translate(lower(titulo), :accented, :unaccented)), 'A')
            || setweight(to_tsvector('portuguese', translate(lower(coalesce(resumo, '')), :accented, :unaccented)), 'B')
            || setweight(to_tsvector('portuguese', translate(lower(
                array_to_string(pagina, ' ') || ' ' || coalesce(array_to_string(secao, ' '), '')
            ), :accented, :unaccented)), 'C')
            || setweight(to_tsvector('portuguese', translate(lower(
                regexp_replace(
                    regexp_replace(coalesce(conteudo, ''), '<[^>]*>', ' ', 'g'),
                    '&[#a-zA-Z0-9]+;', ' ', 'g'
                )
            ), :accented, :unaccented)), 'D') AS documento
        FROM public.base_conhecimento
        WHERE ativo = true
    )
    SELECT idbase_conhecimento, ts_rank(documento, to_tsquery('portuguese', :query)) AS rank
    FROM artigos
    WHERE documento @@ to_tsquery('portuguese', :query)
    ORDER BY rank DESC, idbase_conhecimento
    LIMIT :limit
    """
)

_MAX_SEARCH_TERMS = 30


def _search_terms(query: str) -> list[str]:
    """Words of a free-text question, lowercased and without accents.

    Only [a-z0-9] survive, so the terms are always safe to join into a tsquery.
    """
    normalized = stringutils.remove_accents(query or "").decode("ascii").lower()

    terms = []
    for term in re.findall(r"[a-z0-9]{2,}", normalized):
        if term not in terms:
            terms.append(term)

    return terms[:_MAX_SEARCH_TERMS]


def _pinned_to(request_data) -> list:
    """Filters for the screens/sections an article is pinned to.

    An article matches when it shares any screen with ``path`` or any section
    with ``section``: asking for a screen and its sections returns the union.
    """
    pinned = []
    if request_data.path:
        pinned.append(KnowledgeBase.path.overlap(request_data.path))

    if request_data.section:
        pinned.append(KnowledgeBase.section.overlap(request_data.section))

    return [or_(*pinned)] if pinned else []


def list_knowledge_base(request_data: KnowledgeBaseListRequest) -> list[KnowledgeBase]:
    """List knowledge base records"""
    query = db.session.query(KnowledgeBase)

    if request_data.active is not None:
        query = query.filter(KnowledgeBase.active == request_data.active)

    query = query.filter(*_pinned_to(request_data))

    return query.order_by(KnowledgeBase.title).all()


def list_for_maintenance(
    request_data: KnowledgeBaseManageListRequest,
) -> list[KnowledgeBase]:
    """List knowledge base records for the maintenance screen"""
    query = db.session.query(KnowledgeBase)

    if request_data.active is not None:
        query = query.filter(KnowledgeBase.active == request_data.active)

    query = query.filter(*_pinned_to(request_data))

    if request_data.term and request_data.term.strip():
        term = f"%{request_data.term.strip()}%"
        query = query.filter(
            or_(KnowledgeBase.title.ilike(term), KnowledgeBase.description.ilike(term))
        )

    return query.order_by(KnowledgeBase.title).all()


def get_by_id(id_article: int) -> KnowledgeBase | None:
    """Get a knowledge base record by id"""
    return (
        db.session.query(KnowledgeBase).filter(KnowledgeBase.id == id_article).first()
    )


def upsert(
    request_data: KnowledgeBaseUpsertRequest,
    record: KnowledgeBase | None,
    user_id: int,
) -> KnowledgeBase:
    """Create a record (record is None) or update the given one"""
    now = datetime.today()

    if record is None:
        record = KnowledgeBase()
        record.created_at = now
        record.created_by = user_id
    else:
        record.updated_at = now
        record.updated_by = user_id

    record.title = request_data.title
    record.description = request_data.description
    record.path = request_data.path
    record.section = request_data.section
    record.training_items = request_data.training_items
    record.link = request_data.link
    record.content = request_data.content
    record.active = request_data.active

    db.session.add(record)
    db.session.flush()

    return record


def get_active_by_ids(ids: list[int]) -> list[KnowledgeBase]:
    """The active articles among the given ids"""
    if not ids:
        return []

    return (
        db.session.query(KnowledgeBase)
        .filter(KnowledgeBase.id.in_(ids), KnowledgeBase.active == True)
        .all()
    )


def search(query: str, limit: int) -> list[KnowledgeBase]:
    """Full text search over the active articles, best match first.

    Any word of the question counts (OR): the ranking puts the articles that
    match more words, and match them in the title, on top.
    """
    terms = _search_terms(query)
    if not terms:
        return []

    rows = db.session.execute(
        _SEARCH_SQL,
        {
            "accented": _ACCENTED,
            "unaccented": _UNACCENTED,
            "query": " | ".join(terms),
            "limit": limit,
        },
    ).fetchall()

    ids = [row[0] for row in rows]
    if not ids:
        return []

    records = {
        kb.id: kb
        for kb in db.session.query(KnowledgeBase)
        .filter(KnowledgeBase.id.in_(ids))
        .all()
    }

    return [records[id_article] for id_article in ids if id_article in records]
