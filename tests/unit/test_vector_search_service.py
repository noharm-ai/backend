"""Unit tests for services.vector_search_service.

``search`` is the retrieval half of the support knowledge base: it turns a
question into an embedding with Bedrock, queries an S3 vector index with it and
returns the matches ordered by distance. Both AWS boundaries are mocked, so the
tests pin down the contract that the callers depend on:

* each client is created for the region its own config field names — embeddings
  and the vector index may live in different regions;
* the question is sent to the configured embedding model and the resulting
  vector is what gets queried, with ``max_results`` as ``topK``;
* results come back sorted by ascending distance (closest first), which is what
  ``support_service.get_related_kb`` relies on when it keeps the top articles.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from services import vector_search_service
from services.vector_search_service import SearchConfig

CONFIG_FIELDS = {
    "vector_bucket": "kb-vectors",
    "vector_index": "articles",
    "vector_region": "us-east-1",
    "embedding_model": "amazon.titan-embed-text-v2:0",
    "embedding_region": "sa-east-1",
}

EMBEDDING = [0.1, 0.2, 0.3]


def _vector(distance, article_id):
    """Build a vector match as the s3vectors API returns it."""
    return {
        "key": f"article-{article_id}",
        "distance": distance,
        "metadata": {"article_id": article_id, "article_name": f"Article {article_id}"},
    }


@pytest.fixture
def aws_clients():
    """Replace utils.aws.get_client with per-service mocks.

    Yields ``(get_client, bedrock, s3vectors)``; the bedrock mock already
    answers ``invoke_model`` with EMBEDDING.
    """
    bedrock = MagicMock()
    body = MagicMock()
    body.read.return_value = json.dumps({"embedding": EMBEDDING}).encode("utf-8")
    bedrock.invoke_model.return_value = {"body": body}

    s3vectors = MagicMock()
    s3vectors.query_vectors.return_value = {"vectors": []}

    clients = {"bedrock-runtime": bedrock, "s3vectors": s3vectors}

    with patch.object(
        vector_search_service.aws,
        "get_client",
        side_effect=lambda service_name, region_name=None: clients[service_name],
    ) as get_client:
        yield get_client, bedrock, s3vectors


def test_search_config_defaults_to_five_results():
    """SearchConfig.max_results defaults to 5 when the stored config omits it"""
    config = SearchConfig(**CONFIG_FIELDS)

    assert config.max_results == 5


def test_search_config_rejects_incomplete_config():
    """SearchConfig refuses a config missing a mandatory field"""
    incomplete = {k: v for k, v in CONFIG_FIELDS.items() if k != "vector_bucket"}

    with pytest.raises(ValueError):
        SearchConfig(**incomplete)


def test_search_builds_each_client_in_its_own_region(aws_clients):
    """search creates the bedrock and s3vectors clients in the configured regions"""
    get_client, _, _ = aws_clients

    vector_search_service.search(query="como faço x?", config=SearchConfig(**CONFIG_FIELDS))

    get_client.assert_any_call("bedrock-runtime", region_name="sa-east-1")
    get_client.assert_any_call("s3vectors", region_name="us-east-1")


def test_search_embeds_the_query_with_the_configured_model(aws_clients):
    """search sends the raw question to the configured embedding model"""
    _, bedrock, _ = aws_clients

    vector_search_service.search(query="como faço x?", config=SearchConfig(**CONFIG_FIELDS))

    bedrock.invoke_model.assert_called_once()
    kwargs = bedrock.invoke_model.call_args.kwargs
    assert kwargs["modelId"] == CONFIG_FIELDS["embedding_model"]
    assert json.loads(kwargs["body"]) == {"inputText": "como faço x?"}


def test_search_queries_the_index_with_the_generated_embedding(aws_clients):
    """search queries the vector index with the embedding and the configured topK"""
    _, _, s3vectors = aws_clients
    config = SearchConfig(**CONFIG_FIELDS, max_results=3)

    vector_search_service.search(query="como faço x?", config=config)

    s3vectors.query_vectors.assert_called_once_with(
        vectorBucketName=CONFIG_FIELDS["vector_bucket"],
        indexName=CONFIG_FIELDS["vector_index"],
        queryVector={"float32": EMBEDDING},
        topK=3,
        returnDistance=True,
        returnMetadata=True,
    )


def test_search_returns_matches_closest_first(aws_clients):
    """search orders the matches by ascending distance"""
    _, _, s3vectors = aws_clients
    s3vectors.query_vectors.return_value = {
        "vectors": [_vector(0.9, "c"), _vector(0.1, "a"), _vector(0.5, "b")]
    }

    results = vector_search_service.search(
        query="como faço x?", config=SearchConfig(**CONFIG_FIELDS)
    )

    assert [v["metadata"]["article_id"] for v in results] == ["a", "b", "c"]


def test_search_returns_an_empty_list_when_the_index_has_no_match(aws_clients):
    """search returns an empty list when the index answers with no vector"""
    results = vector_search_service.search(
        query="como faço x?", config=SearchConfig(**CONFIG_FIELDS)
    )

    assert results == []
