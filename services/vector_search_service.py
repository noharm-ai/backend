"""Service: vector search"""

import json

import boto3
from pydantic import BaseModel


class SearchConfig(BaseModel):
    """Search config param"""

    vector_bucket: str
    vector_index: str
    vector_region: str
    embedding_model: str
    embedding_region: str
    max_results: int = 5


def search(query: str, config: SearchConfig) -> dict:
    """Search vector index"""
    bedrock = boto3.client("bedrock-runtime", region_name=config.embedding_region)
    s3vectors = boto3.client("s3vectors", region_name=config.vector_region)

    # Generate the vector embedding.
    embedding_response = bedrock.invoke_model(
        modelId=config.embedding_model,
        body=json.dumps({"inputText": query}),
    )

    # Extract embedding from response.
    model_response = json.loads(embedding_response["body"].read())
    embedding = model_response["embedding"]

    # Query vector index.
    vector_response = s3vectors.query_vectors(
        vectorBucketName=config.vector_bucket,
        indexName=config.vector_index,
        queryVector={"float32": embedding},
        topK=config.max_results,
        returnDistance=True,
        returnMetadata=True,
    )

    vectors = vector_response["vectors"]

    return sorted(
        vectors,
        key=lambda d: d["distance"],
    )
