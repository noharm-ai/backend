"""Tests: POST /support/related-articles

The endpoint suggests knowledge-base articles for a support question. It reads
the vector-index configuration from the global memory (``public.memoria``, kind
``user-kb``), narrows the search to the three closest matches and collapses the
vector hits into a de-duplicated article list.

The retrieval itself talks to Bedrock and to an S3 vector index, neither of
which is reachable from a test, so ``vector_search_service.search`` is replaced
by a stub. That keeps two production-relevant things assertable: the *config*
handed to the search (a wrong bucket or an unbounded ``max_results`` is a real
incident) and how vector hits are folded into articles — the same article is
indexed as many chunks, so duplicates are the normal case rather than the
exception.

``vector_search_service.search`` itself is covered by
``tests/unit/test_vector_search_service.py``.
"""

import json
from unittest.mock import patch

import pytest
from sqlalchemy import text

from models.enums import GlobalMemoryEnum
from services import support_service
from tests.conftest import session, session_commit
from utils import status

URL = "/support/related-articles"

SEARCH_CONFIG = {
    "vector_bucket": "kb-vectors",
    "vector_index": "articles",
    "vector_region": "us-east-1",
    "embedding_model": "amazon.titan-embed-text-v2:0",
    "embedding_region": "sa-east-1",
    "max_results": 10,
}


def _vector(distance, article_id=None, article_name=None):
    """Build a vector hit as the search service returns it.

    Omitting ``article_id`` yields a hit whose metadata does not point at an
    article — content indexed from another source.
    """
    metadata = {}
    if article_id is not None:
        metadata["article_id"] = article_id
    if article_name is not None:
        metadata["article_name"] = article_name

    return {"key": f"chunk-{distance}", "distance": distance, "metadata": metadata}


@pytest.fixture(autouse=True)
def kb_config():
    """Install the user-kb search configuration in the global memory."""
    session.execute(
        text(
            "INSERT INTO public.memoria (tipo, valor, update_at, update_by) "
            "VALUES (:kind, CAST(:value AS json), now(), 1)"
        ),
        {"kind": GlobalMemoryEnum.USER_KB.value, "value": json.dumps(SEARCH_CONFIG)},
    )
    session_commit()

    yield

    session.execute(
        text("DELETE FROM public.memoria WHERE tipo = :kind"),
        {"kind": GlobalMemoryEnum.USER_KB.value},
    )
    session_commit()


@pytest.fixture
def search_mock():
    """Replace the vector search with a stub returning no hit by default."""
    with patch.object(
        support_service.vector_search_service, "search", return_value=[]
    ) as mock:
        yield mock


def test_related_articles_requires_a_question(client, analyst_headers, search_mock):
    """POST /support/related-articles - 400 when the question is empty"""
    response = client.post(URL, json={"question": ""}, headers=analyst_headers)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"
    search_mock.assert_not_called()


def test_related_articles_requires_the_question_field(
    client, analyst_headers, search_mock
):
    """POST /support/related-articles - 400 when the question field is absent"""
    response = client.post(URL, json={}, headers=analyst_headers)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    search_mock.assert_not_called()


def test_related_articles_searches_with_the_stored_config(
    client, analyst_headers, search_mock
):
    """POST /support/related-articles - the search uses the user-kb config, capped at 3"""
    response = client.post(
        URL, json={"question": "como emito o relatório?"}, headers=analyst_headers
    )

    assert response.status_code == status.HTTP_200_OK

    search_mock.assert_called_once()
    kwargs = search_mock.call_args.kwargs
    assert kwargs["query"] == "como emito o relatório?"

    config = kwargs["config"]
    assert config.vector_bucket == SEARCH_CONFIG["vector_bucket"]
    assert config.vector_index == SEARCH_CONFIG["vector_index"]
    assert config.embedding_model == SEARCH_CONFIG["embedding_model"]
    # the stored config allows 10 results; the endpoint narrows it to 3
    assert config.max_results == 3


def test_related_articles_returns_the_matched_articles(
    client, analyst_headers, search_mock
):
    """POST /support/related-articles - each matched article is returned with its name"""
    search_mock.return_value = [
        _vector(0.1, article_id="12", article_name="Emitir relatório"),
        _vector(0.4, article_id="34", article_name="Configurar segmento"),
    ]

    response = client.post(
        URL, json={"question": "relatório"}, headers=analyst_headers
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == [
        {"id": "12", "name": "Emitir relatório"},
        {"id": "34", "name": "Configurar segmento"},
    ]


def test_related_articles_deduplicates_chunks_of_the_same_article(
    client, analyst_headers, search_mock
):
    """POST /support/related-articles - several chunks of one article yield one entry"""
    search_mock.return_value = [
        _vector(0.1, article_id="12", article_name="Emitir relatório"),
        _vector(0.2, article_id="12", article_name="Emitir relatório"),
        _vector(0.3, article_id="34", article_name="Configurar segmento"),
    ]

    response = client.post(
        URL, json={"question": "relatório"}, headers=analyst_headers
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == [
        {"id": "12", "name": "Emitir relatório"},
        {"id": "34", "name": "Configurar segmento"},
    ]


def test_related_articles_ignores_hits_without_an_article(
    client, analyst_headers, search_mock
):
    """POST /support/related-articles - hits whose metadata has no article are dropped"""
    search_mock.return_value = [
        _vector(0.1),
        _vector(0.2, article_id="12", article_name="Emitir relatório"),
    ]

    response = client.post(
        URL, json={"question": "relatório"}, headers=analyst_headers
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == [{"id": "12", "name": "Emitir relatório"}]


def test_related_articles_is_empty_when_nothing_matches(
    client, analyst_headers, search_mock
):
    """POST /support/related-articles - no vector hit means no suggestion"""
    response = client.post(
        URL, json={"question": "assunto inexistente"}, headers=analyst_headers
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == []
