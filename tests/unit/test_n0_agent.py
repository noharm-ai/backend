"""Unit tests for agents.n0_agent — the N0 support assistant.

N0 is the first support line: instead of opening a ticket straight away, the
user asks a question and a Bedrock agent answers it from the NoHarm knowledge
base (``run_n0``), or turns the question into a pre-filled ticket form
(``run_n0_form``). Both read their whole configuration — model ids, regions,
guardrail, prompts, vector index and article bucket — from a single
``public.memoria`` row of kind ``n0-agent``.

Every boundary here is remote (Bedrock, an S3 vector index, the article bucket)
and the agent loop is non-deterministic, so these are unit tests: the global
memory lookup, ``strands.Agent``/``BedrockModel`` and ``utils.aws.get_client``
are mocked. What is worth pinning down is the wiring the production behaviour
depends on:

* the configured model/guardrail/regions actually reach Bedrock — a silently
  dropped guardrail id would let unfiltered answers through;
* the two "do not answer" outcomes (guardrail intervention, Bedrock read
  timeout) come back as the SKIP_ANSWER sentinels the frontend keys on, rather
  than as an exception or a partial answer;
* the knowledge-base tool is called at most once per question, which is the
  only thing stopping a retrieval loop from running up cost;
* a failing retrieval degrades into a polite error payload instead of breaking
  the whole answer.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ReadTimeoutError

from agents import n0_agent
from exception.validation_error import ValidationError
from models.main import User
from models.response.agents.n0_response import TicketForm
from utils import status

N0_CONFIG = {
    "bedrock_model": {
        "model_id": "anthropic.claude-test-v1",
        "region_name": "us-east-1",
        "guardrail_id": "guardrail-test",
        "guardrail_version": "3",
    },
    "embedding_model": {
        "model_id": "amazon.titan-embed-text-test",
        "region_name": "sa-east-1",
    },
    "vector_index": {
        "bucket_name": "kb-vectors",
        "index_name": "articles",
        "region_name": "us-west-2",
        "max_articles": 4,
    },
    "knowledge_base": {"bucket_name": "kb-articles", "path": "artigos"},
    "n0prompt": "Você é o suporte N0 da NoHarm.",
    "n0formprompt": "Monte um chamado a partir da pergunta.",
}

EMBEDDING = [0.1, 0.2, 0.3]


def _user(name="Fulano Beltrano"):
    """A minimal user, as support_service hands it to the agent."""
    user = User()
    user.id = 1
    user.name = name

    return user


def _vector(article_id):
    """A vector match as the s3vectors query returns it.

    ``article_id`` None yields a match whose metadata points at no article.
    """
    metadata = {} if article_id is None else {"article_id": article_id}

    return {"key": f"chunk-{article_id}", "distance": 0.1, "metadata": metadata}


@pytest.fixture
def config_memory():
    """Answer the global-memory lookup with N0_CONFIG."""
    db_mock = MagicMock()
    db_mock.session.query.return_value.filter.return_value.first.return_value = (
        SimpleNamespace(value=N0_CONFIG)
    )

    with patch.object(n0_agent, "db", db_mock):
        yield db_mock


@pytest.fixture
def no_config_memory():
    """Answer the global-memory lookup with no row."""
    db_mock = MagicMock()
    db_mock.session.query.return_value.filter.return_value.first.return_value = None

    with patch.object(n0_agent, "db", db_mock):
        yield db_mock


@pytest.fixture
def agent_mock():
    """Replace strands' Agent and BedrockModel.

    Yields ``(Agent, BedrockModel, agent)`` where ``agent`` is the instance the
    service builds; it answers a call with a non-guardrail result by default.
    """
    agent = MagicMock()
    agent.return_value = MagicMock(stop_reason="end_turn")

    with (
        patch.object(n0_agent, "Agent", return_value=agent) as agent_class,
        patch.object(n0_agent, "BedrockModel") as model_class,
    ):
        yield agent_class, model_class, agent


@pytest.fixture
def aws_clients():
    """Replace utils.aws.get_client with per-service mocks.

    Yields ``(get_client, bedrock, s3vectors, s3)``. The bedrock mock already
    answers ``invoke_model`` with EMBEDDING, the vector index returns no match
    and the article bucket returns a fixed body.
    """
    bedrock = MagicMock()
    body = MagicMock()
    body.read.return_value = json.dumps({"embedding": EMBEDDING}).encode("utf-8")
    bedrock.invoke_model.return_value = {"body": body}

    s3vectors = MagicMock()
    s3vectors.query_vectors.return_value = {"vectors": []}

    s3 = MagicMock()
    article_body = MagicMock()
    article_body.read.return_value = "conteúdo do artigo".encode("utf-8")
    s3.get_object.return_value = {"Body": article_body}

    clients = {"bedrock-runtime": bedrock, "s3vectors": s3vectors, "s3": s3}

    with patch.object(
        n0_agent.aws,
        "get_client",
        side_effect=lambda service_name, region_name=None: clients[service_name],
    ) as get_client:
        yield get_client, bedrock, s3vectors, s3


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------


def test_get_config_returns_the_stored_value(config_memory):
    """The n0-agent global memory row is read as the agent configuration"""
    assert n0_agent._get_config() == N0_CONFIG


def test_get_config_without_the_memory_row_is_rejected(no_config_memory):
    """A missing n0-agent configuration is a server error, not a silent default"""
    with pytest.raises(ValidationError) as error:
        n0_agent._get_config()

    assert error.value.code == "errors.businessRules"
    assert error.value.httpStatus == status.HTTP_500_INTERNAL_SERVER_ERROR


def test_model_config_caps_the_read_timeout():
    """Bedrock calls are bounded by a 20s read timeout"""
    assert n0_agent._get_model_config().read_timeout == 20


# ---------------------------------------------------------------------------
# run_n0
# ---------------------------------------------------------------------------


def test_run_n0_configures_the_model_from_the_memory(config_memory, agent_mock):
    """The Bedrock model is built with the configured id, region and guardrail"""
    _, model_class, _ = agent_mock

    n0_agent.run_n0(query="como emito o relatório?", user=_user())

    kwargs = model_class.call_args.kwargs
    assert kwargs["model_id"] == N0_CONFIG["bedrock_model"]["model_id"]
    assert kwargs["region_name"] == N0_CONFIG["bedrock_model"]["region_name"]
    assert kwargs["guardrail_id"] == N0_CONFIG["bedrock_model"]["guardrail_id"]
    assert (
        kwargs["guardrail_version"] == N0_CONFIG["bedrock_model"]["guardrail_version"]
    )
    assert kwargs["boto_client_config"].read_timeout == 20


def test_run_n0_builds_the_agent_with_the_prompt_and_the_kb_tool(
    config_memory, agent_mock
):
    """The agent gets the n0 system prompt and the knowledge-base tool"""
    agent_class, model_class, _ = agent_mock

    n0_agent.run_n0(query="como emito o relatório?", user=_user())

    kwargs = agent_class.call_args.kwargs
    assert kwargs["system_prompt"] == N0_CONFIG["n0prompt"]
    assert kwargs["model"] is model_class.return_value
    # the HTTP layer returns the final answer, so streaming callbacks are off
    assert kwargs["callback_handler"] is None

    tools = kwargs["tools"]
    assert len(tools) == 1
    assert tools[0].tool_name == "buscar_conhecimento"


def test_run_n0_sends_the_user_name_and_the_question(config_memory, agent_mock):
    """The prompt carries the asking user's name and the question, tagged"""
    _, _, agent = agent_mock

    n0_agent.run_n0(query="como emito o relatório?", user=_user("Ciclano de Tal"))

    prompt = agent.call_args.kwargs["prompt"]
    assert "<nome_do_usuario>Ciclano de Tal</nome_do_usuario>" in prompt
    assert "<pergunta_usuario>como emito o relatório?</pergunta_usuario>" in prompt


def test_run_n0_returns_the_agent_result(config_memory, agent_mock):
    """A normal turn returns the agent result untouched"""
    _, _, agent = agent_mock
    result = MagicMock(stop_reason="end_turn")
    agent.return_value = result

    assert n0_agent.run_n0(query="pergunta", user=_user()) is result


def test_run_n0_skips_the_answer_when_the_guardrail_intervenes(
    config_memory, agent_mock
):
    """A guardrail intervention returns the SKIP sentinel instead of the answer"""
    _, _, agent = agent_mock
    agent.return_value = MagicMock(stop_reason="guardrail_intervened")

    response = n0_agent.run_n0(query="pergunta", user=_user())

    assert response == "SKIP_ANSWER DUE_TO_GUARDRAIL"


def test_run_n0_skips_the_answer_on_a_read_timeout(config_memory, agent_mock):
    """A Bedrock read timeout returns the SKIP sentinel instead of raising"""
    _, _, agent = agent_mock
    agent.side_effect = ReadTimeoutError(endpoint_url="https://bedrock.test")

    response = n0_agent.run_n0(query="pergunta", user=_user())

    assert response == "SKIP_ANSWER DUE_TO_TIMEOUT"


def test_run_n0_propagates_other_errors(config_memory, agent_mock):
    """An error other than a read timeout is not swallowed"""
    _, _, agent = agent_mock
    agent.side_effect = RuntimeError("bedrock exploded")

    with pytest.raises(RuntimeError):
        n0_agent.run_n0(query="pergunta", user=_user())


def test_run_n0_without_the_configuration_is_rejected(no_config_memory, agent_mock):
    """No configuration means no agent is built at all"""
    agent_class, _, _ = agent_mock

    with pytest.raises(ValidationError):
        n0_agent.run_n0(query="pergunta", user=_user())

    agent_class.assert_not_called()


# ---------------------------------------------------------------------------
# run_n0_form
# ---------------------------------------------------------------------------


def _ticket_form():
    """A structured ticket as the form agent returns it."""
    return TicketForm(
        type="Erro",
        subject="Relatório não abre",
        description="O relatório consolidado não abre desde ontem.",
        extra_fields=[{"label": "Print da tela", "type": "archive"}],
    )


def test_run_n0_form_uses_the_form_prompt(config_memory, agent_mock):
    """The form agent runs with the n0form system prompt"""
    agent_class, _, agent = agent_mock
    agent.structured_output.return_value = _ticket_form()

    n0_agent.run_n0_form(query="o relatório não abre")

    assert agent_class.call_args.kwargs["system_prompt"] == N0_CONFIG["n0formprompt"]


def test_run_n0_form_does_not_expose_the_knowledge_base(config_memory, agent_mock):
    """The form agent has no tools: it only reshapes the question"""
    agent_class, _, agent = agent_mock
    agent.structured_output.return_value = _ticket_form()

    n0_agent.run_n0_form(query="o relatório não abre")

    assert "tools" not in agent_class.call_args.kwargs


def test_run_n0_form_model_has_no_guardrail(config_memory, agent_mock):
    """The form model is built without the guardrail used for free answers"""
    _, model_class, agent = agent_mock
    agent.structured_output.return_value = _ticket_form()

    n0_agent.run_n0_form(query="o relatório não abre")

    kwargs = model_class.call_args.kwargs
    assert kwargs["model_id"] == N0_CONFIG["bedrock_model"]["model_id"]
    assert kwargs["region_name"] == N0_CONFIG["bedrock_model"]["region_name"]
    assert "guardrail_id" not in kwargs


def test_run_n0_form_returns_the_ticket_as_a_dict(config_memory, agent_mock):
    """The structured ticket comes back serialized for the HTTP response"""
    _, _, agent = agent_mock
    agent.structured_output.return_value = _ticket_form()

    response = n0_agent.run_n0_form(query="o relatório não abre")

    assert response == {
        "type": "Erro",
        "subject": "Relatório não abre",
        "description": "O relatório consolidado não abre desde ontem.",
        "extra_fields": [{"label": "Print da tela", "type": "archive"}],
    }


def test_run_n0_form_asks_for_the_ticket_schema(config_memory, agent_mock):
    """The question is sent tagged, with TicketForm as the expected output"""
    _, _, agent = agent_mock
    agent.structured_output.return_value = _ticket_form()

    n0_agent.run_n0_form(query="o relatório não abre")

    model, prompt = agent.structured_output.call_args.args
    assert model is TicketForm
    assert prompt == "<pergunta_usuario>o relatório não abre</pergunta_usuario>"


# ---------------------------------------------------------------------------
# knowledge-base tool
# ---------------------------------------------------------------------------


def test_kb_tool_is_named_for_the_agent():
    """The tool is exposed under the name the system prompt refers to"""
    get_kb = n0_agent.wrap_kb(N0_CONFIG)

    assert get_kb.tool_name == "buscar_conhecimento"
    assert "UMA VEZ" in get_kb.tool_spec["description"]


def test_kb_tool_searches_with_the_query(aws_clients):
    """The first call reaches the retrieval with the agent's query"""
    _, bedrock, _, _ = aws_clients
    get_kb = n0_agent.wrap_kb(N0_CONFIG)

    get_kb("emitir relatório")

    payload = json.loads(bedrock.invoke_model.call_args.kwargs["body"])
    assert payload["inputText"] == "emitir relatório"


def test_kb_tool_is_called_only_once_per_question(aws_clients):
    """A second call returns the cached result without querying again"""
    _, bedrock, s3vectors, _ = aws_clients
    get_kb = n0_agent.wrap_kb(N0_CONFIG)

    first = get_kb("emitir relatório")
    second = get_kb("outra busca completamente diferente")

    assert second == first
    bedrock.invoke_model.assert_called_once()
    s3vectors.query_vectors.assert_called_once()


def test_kb_tool_call_limit_is_per_wrap(aws_clients):
    """Each question gets a fresh budget: the limit does not leak between turns"""
    _, bedrock, _, _ = aws_clients

    n0_agent.wrap_kb(N0_CONFIG)("primeira pergunta")
    n0_agent.wrap_kb(N0_CONFIG)("segunda pergunta")

    assert bedrock.invoke_model.call_count == 2


# ---------------------------------------------------------------------------
# retrieval
# ---------------------------------------------------------------------------


def test_knowledge_base_uses_the_configured_regions(aws_clients):
    """Embeddings, the vector index and the article bucket use their own regions"""
    get_client, _, _, _ = aws_clients

    n0_agent._get_knowledge_base(query="pergunta", config=N0_CONFIG)

    regions = {
        call.args[0] if call.args else call.kwargs["service_name"]: call.kwargs[
            "region_name"
        ]
        for call in get_client.call_args_list
    }
    assert regions["bedrock-runtime"] == N0_CONFIG["embedding_model"]["region_name"]
    assert regions["s3vectors"] == N0_CONFIG["vector_index"]["region_name"]
    assert regions["s3"] == N0_CONFIG["vector_index"]["region_name"]


def test_knowledge_base_queries_the_index_with_the_embedding(aws_clients):
    """The generated embedding is what the vector index is queried with"""
    _, bedrock, s3vectors, _ = aws_clients

    n0_agent._get_knowledge_base(query="pergunta", config=N0_CONFIG)

    assert (
        bedrock.invoke_model.call_args.kwargs["modelId"]
        == N0_CONFIG["embedding_model"]["model_id"]
    )

    kwargs = s3vectors.query_vectors.call_args.kwargs
    assert kwargs["vectorBucketName"] == N0_CONFIG["vector_index"]["bucket_name"]
    assert kwargs["indexName"] == N0_CONFIG["vector_index"]["index_name"]
    assert kwargs["queryVector"] == {"float32": EMBEDDING}
    assert kwargs["topK"] == N0_CONFIG["vector_index"]["max_articles"]


def test_knowledge_base_without_matches_returns_no_article(aws_clients):
    """An empty index answer is a success with zero articles, not an error"""
    result = n0_agent._get_knowledge_base(query="pergunta", config=N0_CONFIG)

    assert result["status"] == "success"
    assert result["content"][0]["json"] == {"articles": [], "total": 0}


def test_knowledge_base_reads_each_matched_article(aws_clients):
    """Matched articles are fetched from the configured bucket and path"""
    _, _, s3vectors, s3 = aws_clients
    s3vectors.query_vectors.return_value = {"vectors": [_vector("42")]}

    result = n0_agent._get_knowledge_base(query="pergunta", config=N0_CONFIG)

    s3.get_object.assert_called_once_with(
        Bucket=N0_CONFIG["knowledge_base"]["bucket_name"],
        Key="artigos/article_42.txt",
    )

    payload = result["content"][0]["json"]
    assert payload["total"] == 1
    assert payload["articles"][0] == {
        "article_id": "42",
        "content": "conteúdo do artigo",
    }


def test_knowledge_base_deduplicates_chunks_of_the_same_article(aws_clients):
    """An article indexed as several chunks is downloaded and returned once"""
    _, _, s3vectors, s3 = aws_clients
    s3vectors.query_vectors.return_value = {
        "vectors": [_vector("42"), _vector("42"), _vector("42")]
    }

    result = n0_agent._get_knowledge_base(query="pergunta", config=N0_CONFIG)

    s3.get_object.assert_called_once()
    assert result["content"][0]["json"]["total"] == 1


def test_knowledge_base_ignores_matches_without_an_article(aws_clients):
    """A match whose metadata names no article is skipped"""
    _, _, s3vectors, s3 = aws_clients
    s3vectors.query_vectors.return_value = {"vectors": [_vector(None), _vector("7")]}

    result = n0_agent._get_knowledge_base(query="pergunta", config=N0_CONFIG)

    s3.get_object.assert_called_once()
    assert result["content"][0]["json"]["articles"][0]["article_id"] == "7"


def test_knowledge_base_failure_degrades_into_a_message(aws_clients):
    """A retrieval failure returns a readable payload instead of raising"""
    _, bedrock, _, _ = aws_clients
    bedrock.invoke_model.side_effect = RuntimeError("bedrock unavailable")

    result = n0_agent._get_knowledge_base(query="pergunta", config=N0_CONFIG)

    assert result["status"] == "error"
    assert "erro" in result["content"][0]["text"].lower()


def test_kb_tool_caches_the_error_result_too(aws_clients):
    """A failed retrieval still consumes the single call budget"""
    _, bedrock, _, _ = aws_clients
    bedrock.invoke_model.side_effect = RuntimeError("bedrock unavailable")
    get_kb = n0_agent.wrap_kb(N0_CONFIG)

    first = get_kb("pergunta")
    second = get_kb("pergunta")

    assert first["status"] == "error"
    assert second == first
    bedrock.invoke_model.assert_called_once()


# ---------------------------------------------------------------------------
# retrieval from the articles registered in NoHarm (knowledge_base.source)
# ---------------------------------------------------------------------------

DB_CONFIG = {
    **N0_CONFIG,
    "knowledge_base": {"source": "database", "max_articles": 3},
}


def _kb(id_article, content="<p>Clique em <b>Checar</b>.</p>", link=None):
    """A knowledge base row, as the repository search returns it."""
    return SimpleNamespace(
        id=id_article,
        title=f"Artigo {id_article}",
        description="Resumo do artigo",
        path=["Prescrição"],
        section=["prescricao.exames"],
        content=content,
        link=link,
    )


def test_database_source_searches_the_registered_articles(aws_clients):
    """With source=database the tool reads public.base_conhecimento, not S3"""
    get_client, _, _, _ = aws_clients

    with patch.object(
        n0_agent.knowledge_base_repository, "search", return_value=[_kb(7)]
    ) as search:
        result = n0_agent._get_knowledge_base(query="pergunta", config=DB_CONFIG)

    search.assert_called_once_with(query="pergunta", limit=3)
    get_client.assert_not_called()

    payload = result["content"][0]["json"]
    assert result["status"] == "success"
    assert payload["total"] == 1
    assert payload["articles"][0]["article_id"] == 7
    assert payload["articles"][0]["pages"] == ["Prescrição"]
    assert payload["articles"][0]["sections"] == ["prescricao.exames"]


def test_database_source_hands_the_agent_plain_text(aws_clients):
    """The article body reaches the agent without the editor markup"""
    article = _kb(7, link="https://kb.example.com/artigo")

    with patch.object(
        n0_agent.knowledge_base_repository, "search", return_value=[article]
    ):
        result = n0_agent._get_knowledge_base(query="pergunta", config=DB_CONFIG)

    content = result["content"][0]["json"]["articles"][0]["content"]
    assert "Artigo 7" in content
    assert "Resumo do artigo" in content
    assert "Clique em Checar." in content
    assert "<" not in content
    assert "https://kb.example.com/artigo" in content


def test_database_source_default_article_limit(aws_clients):
    """Without max_articles the search is capped at the default"""
    config = {**N0_CONFIG, "knowledge_base": {"source": "database"}}

    with patch.object(
        n0_agent.knowledge_base_repository, "search", return_value=[]
    ) as search:
        n0_agent._get_knowledge_base(query="pergunta", config=config)

    search.assert_called_once_with(
        query="pergunta", limit=n0_agent.DEFAULT_MAX_ARTICLES
    )


def test_database_source_failure_degrades_into_a_message(aws_clients):
    """A failing database search still answers the agent with the error payload"""
    with patch.object(
        n0_agent.knowledge_base_repository, "search", side_effect=RuntimeError("db")
    ):
        result = n0_agent._get_knowledge_base(query="pergunta", config=DB_CONFIG)

    assert result["status"] == "error"
    assert "text" in result["content"][0]
