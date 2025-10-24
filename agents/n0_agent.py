"""Agent: N0 Agent"""

import json
import logging

import boto3
from botocore.config import Config
from botocore.exceptions import ReadTimeoutError
from strands import Agent, tool
from strands.models import BedrockModel

from models.response.agents.n0_response import TicketForm
from models.main import db, User
from models.appendix import GlobalMemory
from models.enums import GlobalMemoryEnum
from exception.validation_error import ValidationError
from utils import status

logging.basicConfig()
logger = logging.getLogger("noharm.backend")


def _get_config():
    config = (
        db.session.query(GlobalMemory)
        .filter(GlobalMemory.kind == GlobalMemoryEnum.N0_AGENT.value)
        .first()
    )

    if not config:
        raise ValidationError(
            "Configuração do agente N0 não encontrada.",
            "errors.businessRules",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return config.value


def _get_model_config():
    """Get the model configuration for the n0 agent."""

    return Config(
        read_timeout=20,
    )


def run_n0(query: str, user: User) -> str:
    """Process a user query with the n0 agent."""

    config = _get_config()

    bedrock_model = BedrockModel(
        model_id=config["bedrock_model"]["model_id"],
        region_name=config["bedrock_model"]["region_name"],
        boto_client_config=_get_model_config(),
    )

    get_kb = wrap_kb(config)

    agent = Agent(
        tools=[get_kb],
        system_prompt=config["n0prompt"],
        model=bedrock_model,
        callback_handler=None,
    )

    try:
        return agent(
            prompt=f"<nome_do_usuario>{user.name}</nome_do_usuario><pergunta_usuario>{query}</pergunta_usuario>"
        )
    except ReadTimeoutError:
        logger.warning(
            "VALIDATION4xx: NZERO Timeout ao processar a consulta do usuário: %s", query
        )
        return "SKIP_ANSWER DUE_TO_TIMEOUT"


def run_n0_form(query: str) -> str:
    """Process a user query with the n0 form agent."""

    config = _get_config()

    bedrock_model = BedrockModel(
        model_id=config["bedrock_model"]["model_id"],
        region_name=config["bedrock_model"]["region_name"],
    )

    agent = Agent(
        system_prompt=config["n0formprompt"],
        model=bedrock_model,
        callback_handler=None,
    )

    return agent.structured_output(
        TicketForm, f"<pergunta_usuario>{query}</pergunta_usuario>"
    ).model_dump()


def wrap_kb(config: dict):
    """Wrap the knowledge base tool for the agent."""

    @tool(
        name="buscar_conhecimento",
        description="Busca informações na base de conhecimento da NoHarm.",
    )
    def get_kb(query: str) -> dict:
        """Tool to get knowledge base articles."""
        return _get_knowledge_base(query=query, config=config)

    return get_kb


def _get_knowledge_base(query: str, config: dict) -> dict:
    """Get the knowledge base for the agent."""

    try:
        logger.info("Iniciando busca na base de conhecimento com a consulta: %s", query)

        bedrock = boto3.client(
            "bedrock-runtime", region_name=config["embedding_model"]["region_name"]
        )
        s3vectors = boto3.client(
            "s3vectors", region_name=config["vector_index"]["region_name"]
        )
        s3_client = boto3.client(
            "s3", region_name=config["vector_index"]["region_name"]
        )

        # Generate the vector embedding.
        embedding_response = bedrock.invoke_model(
            modelId=config["embedding_model"]["model_id"],
            body=json.dumps({"inputText": query}),
        )

        # Extract embedding from response.
        model_response = json.loads(embedding_response["body"].read())
        embedding = model_response["embedding"]

        # Query vector index.
        vector_response = s3vectors.query_vectors(
            vectorBucketName=config["vector_index"]["bucket_name"],
            indexName=config["vector_index"]["index_name"],
            queryVector={"float32": embedding},
            topK=config["vector_index"]["max_articles"],
            returnDistance=True,
            returnMetadata=True,
        )

        vectors = vector_response["vectors"]

        logger.info(
            "Encontrados %d vetores correspondentes na base de conhecimento.",
            len(vectors),
        )

        articles = []
        article_ids = set()
        for vector in vectors:
            article_id = vector["metadata"].get("article_id", None)
            if article_id:
                article_ids.add(article_id)

        for article_id in article_ids:
            filename = f"{config['knowledge_base']['path']}/article_{article_id}.txt"
            s3_response_object = s3_client.get_object(
                Bucket=config["knowledge_base"]["bucket_name"], Key=filename
            )
            object_content = s3_response_object["Body"].read().decode("utf-8")

            articles.append(
                {
                    "article_id": article_id,
                    "content": object_content,
                }
            )

        return {
            "status": "success",
            "content": [
                {
                    "json": {
                        "articles": articles,
                        "total": len(articles),
                    },
                }
            ],
        }
    except Exception as e:
        logger.error("Error in _get_knowledge_base: %s", str(e))
        return {
            "status": "error",
            "content": [
                {
                    "text": "Desculpe, ocorreu um erro ao buscar informações na base de conhecimento. Por favor, tente novamente mais tarde.",
                }
            ],
        }
