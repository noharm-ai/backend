"""Service: keep the knowledge base articles on the n0 agent vector index

Articles written in NoHarm are embedded and written to the same S3 vector index
the n0 agent searches (``vector_index`` and ``embedding_model`` of the n0-agent
global memory), next to the ODOO articles. Their vectors are told apart by the
key prefix and by ``metadata.source``: the agent reads a NoHarm article from
the database (``metadata.kb_id``), an ODOO one from the article bucket
(``metadata.article_id``). The two id spaces overlap, hence the namespacing.
"""

import json
import logging
from dataclasses import dataclass, field

from models.appendix import GlobalMemory
from models.enums import GlobalMemoryEnum
from models.main import db
from utils import aws, htmlutils

logger = logging.getLogger("noharm.backend")

VECTOR_SOURCE = "noharm"

# an article is split in chunks of about this many characters (paragraphs are
# never cut unless a single one is longer than that)
CHUNK_SIZE = 1500
# chunks beyond this are not indexed: it also bounds the keys to clean up
MAX_CHUNKS = 20


class IndexStatus:
    """Outcome of an index operation, as reported to the maintainer"""

    INDEXED = "indexed"  # the article vectors are up to date
    REMOVED = "removed"  # inactive article: its vectors were deleted
    DISABLED = "disabled"  # no vector index configured for this environment
    FAILED = "failed"  # AWS error: the article must be reindexed later


@dataclass
class ArticleDocument:
    """What gets indexed from an article, detached from the database session"""

    id: int
    title: str
    active: bool
    description: str | None = None
    content: str | None = None
    lessons: list[str] = field(default_factory=list)


def vector_key(id_article: int, chunk: int) -> str:
    """The vector key of an article chunk"""
    return f"{VECTOR_SOURCE}-kb-{id_article}-{chunk}"


def _get_config() -> dict | None:
    """The index/embedding config of the n0 agent, None when incomplete"""
    memory = (
        db.session.query(GlobalMemory)
        .filter(GlobalMemory.kind == GlobalMemoryEnum.N0_AGENT.value)
        .first()
    )
    config = memory.value if memory else None

    if (
        not config
        or not config.get("vector_index", {}).get("bucket_name")
        or not config.get("vector_index", {}).get("index_name")
        or not config.get("embedding_model", {}).get("model_id")
    ):
        return None

    return config


def _paragraphs(document: ArticleDocument) -> list[str]:
    """The article as plain text paragraphs"""
    paragraphs = []

    if document.description:
        paragraphs.append(document.description)

    body = "".join(text for text, _ in htmlutils.html_to_runs(document.content or ""))
    paragraphs.extend(p.strip() for p in body.split("\n") if p.strip())

    if document.lessons:
        paragraphs.append(
            "Aulas de treinamento relacionadas: " + "; ".join(document.lessons)
        )

    return paragraphs


def build_chunks(document: ArticleDocument) -> list[str]:
    """Split the article in chunks, each one starting with the title so a match
    on any chunk still knows which article it belongs to"""
    chunks = []
    current = ""

    for paragraph in _paragraphs(document):
        while len(paragraph) > CHUNK_SIZE:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(paragraph[:CHUNK_SIZE])
            paragraph = paragraph[CHUNK_SIZE:]

        if current and len(current) + len(paragraph) + 1 > CHUNK_SIZE:
            chunks.append(current)
            current = ""

        current = f"{current}\n{paragraph}" if current else paragraph

    if current:
        chunks.append(current)

    if not chunks:
        chunks = [""]

    return [f"{document.title}\n\n{chunk}".strip() for chunk in chunks[:MAX_CHUNKS]]


def _embed(text: str, config: dict) -> list[float]:
    """Embedding of a text with the configured model"""
    bedrock = aws.get_client(
        "bedrock-runtime", region_name=config["embedding_model"].get("region_name")
    )
    response = bedrock.invoke_model(
        modelId=config["embedding_model"]["model_id"],
        body=json.dumps({"inputText": text}),
    )

    return json.loads(response["body"].read())["embedding"]


def _s3vectors(config: dict):
    """The S3 vectors client of the configured index"""
    return aws.get_client(
        "s3vectors", region_name=config["vector_index"].get("region_name")
    )


def _delete_chunks(id_article: int, keep: int, config: dict):
    """Delete the article vectors from chunk ``keep`` on (all of them for 0)"""
    client = _s3vectors(config)
    index = {
        "vectorBucketName": config["vector_index"]["bucket_name"],
        "indexName": config["vector_index"]["index_name"],
    }
    candidates = [vector_key(id_article, n) for n in range(keep, MAX_CHUNKS)]
    if not candidates:
        return

    existing = client.get_vectors(
        **index, keys=candidates, returnData=False, returnMetadata=False
    ).get("vectors", [])
    keys = [vector["key"] for vector in existing]

    if keys:
        client.delete_vectors(**index, keys=keys)


def index_article(document: ArticleDocument) -> str:
    """Bring the article vectors up to date: write them for an active article,
    delete them for an inactive one. Never raises: returns an IndexStatus"""
    try:
        config = _get_config()
        if config is None:
            return IndexStatus.DISABLED

        if not document.active:
            _delete_chunks(document.id, keep=0, config=config)
            return IndexStatus.REMOVED

        chunks = build_chunks(document)
        vectors = [
            {
                "key": vector_key(document.id, n),
                "data": {"float32": _embed(chunk, config)},
                "metadata": {
                    "source": VECTOR_SOURCE,
                    "kb_id": document.id,
                    "article_name": document.title,
                    "chunk": n,
                },
            }
            for n, chunk in enumerate(chunks)
        ]

        _s3vectors(config).put_vectors(
            vectorBucketName=config["vector_index"]["bucket_name"],
            indexName=config["vector_index"]["index_name"],
            vectors=vectors,
        )

        # an edit may have shortened the article: drop the leftover chunks
        _delete_chunks(document.id, keep=len(chunks), config=config)

        return IndexStatus.INDEXED
    except Exception as e:
        logger.error(
            "Error indexing knowledge base article %s: %s", document.id, str(e)
        )
        return IndexStatus.FAILED
