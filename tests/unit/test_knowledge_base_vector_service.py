"""Unit tests for services.knowledge_base_vector_service

Saving an article writes it to the S3 vector index the n0 agent searches, next
to the ODOO articles. What matters here:

* the vectors are namespaced (key prefix + ``metadata.source``/``kb_id``), so
  a NoHarm article never collides with the ODOO article of the same id;
* every chunk carries the title, and a long article is split without losing
  text;
* editing an article to something shorter removes its leftover chunks, and an
  unpublished article is removed from the index altogether;
* a missing configuration or an AWS failure never breaks the save: the outcome
  is reported as a status instead.

Bedrock, S3 vectors and the global memory lookup are mocked.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services import knowledge_base_vector_service as service
from services.knowledge_base_vector_service import ArticleDocument, IndexStatus

CONFIG = {
    "embedding_model": {"model_id": "amazon.titan-embed-test", "region_name": "r1"},
    "vector_index": {
        "bucket_name": "kb-vectors",
        "index_name": "articles",
        "region_name": "r2",
    },
}


def _document(**overrides):
    """An active article with a short body."""
    values = {
        "id": 7,
        "title": "Checagem de prescrição",
        "active": True,
        "description": "Como checar",
        "content": "<p>Clique em <b>Checar</b>.</p>",
        "lessons": ["Módulo Prescrição › Checagem"],
    }
    values.update(overrides)

    return ArticleDocument(**values)


@pytest.fixture
def aws():
    """Mock the config lookup and the AWS clients; yields (bedrock, s3vectors)."""
    bedrock = MagicMock()

    def invoke_model(modelId, body):  # noqa: N803 - boto3 argument name
        payload = MagicMock()
        payload.read.return_value = json.dumps(
            {"embedding": [float(len(json.loads(body)["inputText"]))]}
        ).encode("utf-8")
        return {"body": payload}

    bedrock.invoke_model.side_effect = invoke_model

    s3vectors = MagicMock()
    s3vectors.get_vectors.return_value = {"vectors": []}

    clients = {"bedrock-runtime": bedrock, "s3vectors": s3vectors}

    with (
        patch.object(service, "_get_config", return_value=CONFIG),
        patch.object(
            service.aws,
            "get_client",
            side_effect=lambda name, region_name=None: clients[name],
        ),
    ):
        yield bedrock, s3vectors


def test_active_article_is_written_with_namespaced_vectors(aws):
    """The chunks go to the configured index, told apart from ODOO articles"""
    _, s3vectors = aws

    assert service.index_article(_document()) == IndexStatus.INDEXED

    call = s3vectors.put_vectors.call_args.kwargs
    assert call["vectorBucketName"] == "kb-vectors"
    assert call["indexName"] == "articles"
    assert len(call["vectors"]) == 1
    vector = call["vectors"][0]
    assert vector["key"] == "noharm-kb-7-0"
    assert vector["metadata"] == {
        "source": "noharm",
        "kb_id": 7,
        "article_name": "Checagem de prescrição",
        "chunk": 0,
    }
    assert "float32" in vector["data"]


def test_the_embedded_text_is_plain_and_complete(aws):
    """Title, summary, body without markup and the related lessons"""
    bedrock, _ = aws

    service.index_article(_document())

    text = json.loads(bedrock.invoke_model.call_args.kwargs["body"])["inputText"]
    assert text.startswith("Checagem de prescrição")
    assert "Como checar" in text
    assert "Clique em Checar." in text
    assert "<" not in text
    assert "Módulo Prescrição › Checagem" in text


def test_long_article_is_split_keeping_the_title_on_every_chunk():
    """No text is lost and every chunk says which article it belongs to"""
    paragraphs = [f"Parágrafo {n} " + "x" * 600 for n in range(6)]
    document = _document(content="".join(f"<p>{p}</p>" for p in paragraphs), lessons=[])

    chunks = service.build_chunks(document)

    assert len(chunks) > 1
    assert all(chunk.startswith("Checagem de prescrição") for chunk in chunks)
    assert all(len(chunk) <= service.CHUNK_SIZE + 100 for chunk in chunks)
    joined = "\n".join(chunks)
    assert all(p in joined for p in paragraphs)


def test_chunks_are_capped():
    """A huge article never produces more than MAX_CHUNKS vectors"""
    document = _document(content="<p>" + "y" * 100_000 + "</p>")

    assert len(service.build_chunks(document)) == service.MAX_CHUNKS


def test_shortened_article_loses_its_leftover_chunks(aws):
    """Chunks the new version no longer has are deleted"""
    _, s3vectors = aws
    s3vectors.get_vectors.return_value = {
        "vectors": [{"key": "noharm-kb-7-1"}, {"key": "noharm-kb-7-2"}]
    }

    service.index_article(_document())

    asked = s3vectors.get_vectors.call_args.kwargs["keys"]
    assert "noharm-kb-7-0" not in asked
    assert asked[0] == "noharm-kb-7-1"
    s3vectors.delete_vectors.assert_called_once_with(
        vectorBucketName="kb-vectors",
        indexName="articles",
        keys=["noharm-kb-7-1", "noharm-kb-7-2"],
    )


def test_nothing_to_delete_skips_the_delete_call(aws):
    """No leftover chunk, no delete request"""
    _, s3vectors = aws

    service.index_article(_document())

    s3vectors.delete_vectors.assert_not_called()


def test_inactive_article_is_removed_from_the_index(aws):
    """Unpublishing an article deletes all its vectors and embeds nothing"""
    bedrock, s3vectors = aws
    s3vectors.get_vectors.return_value = {"vectors": [{"key": "noharm-kb-7-0"}]}

    assert service.index_article(_document(active=False)) == IndexStatus.REMOVED

    bedrock.invoke_model.assert_not_called()
    s3vectors.put_vectors.assert_not_called()
    assert s3vectors.get_vectors.call_args.kwargs["keys"][0] == "noharm-kb-7-0"
    s3vectors.delete_vectors.assert_called_once()


def test_without_configuration_indexing_is_disabled():
    """An environment without an n0 vector index just skips indexing"""
    with (
        patch.object(service, "_get_config", return_value=None),
        patch.object(service.aws, "get_client") as get_client,
    ):
        assert service.index_article(_document()) == IndexStatus.DISABLED

    get_client.assert_not_called()


def test_aws_failure_is_reported_not_raised(aws):
    """A failing index write never breaks the save of the article"""
    _, s3vectors = aws
    s3vectors.put_vectors.side_effect = RuntimeError("throttled")

    assert service.index_article(_document()) == IndexStatus.FAILED


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"vector_index": {"bucket_name": "b", "index_name": "i"}},
        {"embedding_model": {"model_id": "m"}, "vector_index": {"bucket_name": "b"}},
    ],
)
def test_incomplete_configuration_counts_as_missing(value):
    """Only a complete index + embedding configuration enables indexing"""
    db_mock = MagicMock()
    db_mock.session.query.return_value.filter.return_value.first.return_value = (
        SimpleNamespace(value=value) if value is not None else None
    )

    with patch.object(service, "db", db_mock):
        assert service._get_config() is None
