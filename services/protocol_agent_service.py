"""Service: conversational protocol creation co-pilot.

Runs a Strands agent (Bedrock) in-process: the frontend holds the chat
transcript and sends it on every turn together with the current form draft;
the agent interviews the user, resolves catalog IDs through read-only tools
and returns a structured turn output. Any proposal is validated with the
same rules applied on protocol upsert before it reaches the client.
"""

import json
import re

from botocore.config import Config as BotoConfig
from botocore.exceptions import ReadTimeoutError
from strands import Agent
from strands.models import BedrockModel
from strands.tools.executors import SequentialToolExecutor
from strands.types.agent import Limits

from config import Config
from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.enums import ProtocolTypeEnum, ProtocolVariableFieldEnum
from models.main import User
from models.requests.protocol_agent_request import ProtocolAgentChatRequest
from models.response.agents.protocol_agent_response import ProtocolAgentTurnOutput
from services.admin import admin_protocol_service
from services.protocol_agent_tools import build_tools
from utils import logger, status
from utils.alert_protocol import SAFE_LOGICAL_EXPR_REGEX

BEDROCK_READ_TIMEOUT = 20
MAX_MESSAGE_LENGTH = 4000
MAX_PROPOSAL_VARIABLES = 50
MAX_TRIGGER_LENGTH = 500
RESULT_LEVELS = {"low", "medium", "high"}

# Per-item criteria of a "combination" variable. They live as flat sibling keys
# of the variable itself (that is what the form renders and what
# utils.alert_protocol reads), but the model likes to wrap them in an object
# under "value" / "combination", which would reach the client as a combo with no
# criteria — silently matching every prescription item. Normalization unwraps it.
COMBINATION_CRITERIA_FIELDS = (
    "substance",
    "class",
    "drug",
    "drugAttribute",
    "route",
    "intravenous",
    "feedingTube",
    "dose",
    "doseOperator",
    "defaultMeasureUnit",
    "frequencyday",
    "frequencydayOperator",
    "period",
    "periodOperator",
    "observation",
)
COMBINATION_NESTED_KEYS = ("value", "combination", "criteria")

LIMIT_TURNS_MESSAGE = (
    "Não consegui concluir a análise dentro do limite desta rodada. "
    "Tente dividir o pedido em etapas menores ou envie uma nova mensagem "
    "para continuar."
)

AGENT_SYSTEM_PROMPT = (
    "You are a co-pilot embedded in NoHarm, a clinical pharmacy decision-support "
    "system. You help staff users create protocols: alert rules evaluated "
    "against prescriptions. You interview the user in Brazilian Portuguese, "
    "look up real catalog data with your tools and, when you have enough "
    "information, produce a complete protocol proposal.\n\n"
    "PROTOCOL STRUCTURE\n"
    "- protocolType: 1 = prescrição agregada, 2 = prescrição individual, "
    "3 = todas as prescrições, 4 = item prescrito (this one REQUIRES a "
    "variable with field 'combination').\n"
    "- config.variables: boolean variables, each pre-evaluated by the system "
    "at runtime. Every variable has: name (short identifier, e.g. var_1), "
    "field, operator, value — except field 'combination', which has neither "
    "operator nor value (see below). Optional per-variable message: "
    '{"if": true|false, "then": "<text shown when the variable equals if>"}.\n'
    "- config.trigger: expression combining variables as {{name}} with "
    '"and", "or", "not" and parentheses (Python precedence: or < and < not). '
    "Nothing else is allowed — no literals, no comparisons, no function "
    "calls. Maximum 500 characters.\n"
    '- config.result: {"type": "SHOW_MESSAGE", "level": "low"|"medium"|"high", '
    '"message": "<short alert>", "description": "<longer explanation>"}.\n\n'
    "VARIABLE FIELDS (field → operator → value)\n"
    "- substance → IN/NOTIN → list of sctid strings (resolve with "
    "search_substances).\n"
    "- class → IN/NOTIN → list of class ids (search_substance_classes).\n"
    "- idDrug → IN/NOTIN → list of idDrug strings (search_drugs).\n"
    "- route → IN/NOTIN → list of route ids (list_routes).\n"
    "- idDepartment → IN/NOTIN → list of idDepartment strings (list_departments).\n"
    "- idSegment → IN/NOTIN → list of segment ids (list_segments).\n"
    "- idIcd → IN/NOTIN → list of ICD ids (search_icds).\n"
    "- exam_ref → > < >= <= = != → number; requires examRefType "
    "(list_reference_exams); optional examRefPeriod (max age of the exam, "
    "in days). PREFERRED field for exam-based criteria.\n"
    "- exam → > < >= <= = != → number; requires examType (list_exam_types); "
    "optional examPeriod. Fallback only: use exam_ref instead whenever the "
    "exam exists in list_reference_exams.\n"
    "- age, weight, admissionTime (hours since admission), stConcilia → "
    "> < >= <= = != → number.\n"
    "- cn_stats → > < >= <= = != → number; requires statsType.\n"
    "- dischargeReason, insurance → CONTAINS → text.\n"
    "- segmentType → IN/NOTIN → list.\n"
    "- combination (only for protocolType 4): per-item criteria. True when ANY "
    "prescription item matches ALL the filled criteria. This field has NO "
    "operator and NO value: every criterion is a FLAT key of the variable "
    "itself. NEVER nest them inside an object. Available criteria: substance "
    "(list of sctid), class (list), drug (list of idDrug), route (list of "
    "route ids from list_routes, compared verbatim against the route of the "
    "prescribed item — copy the id exactly, including case), drugAttribute "
    "(list of: mav = alta vigilância, antimicro, controlled, dialyzable, "
    "elderly = inapropriado para idosos, notdefault = não padronizado, "
    "chemo = quimioterápico; no other value exists), intravenous "
    "(true/false), feedingTube (true/false), dose + doseOperator, "
    "defaultMeasureUnit (mg|ml|mcg|UI, the unit the dose is expressed in), "
    "frequencyday + frequencydayOperator, period + periodOperator, "
    "observation (free text). Correct shape:\n"
    '{"name": "dipirona_dose_alta", "field": "combination", '
    '"substance": ["22165008"], "route": ["ORAL"], "dose": 200, '
    '"doseOperator": ">", "defaultMeasureUnit": "mg"}\n'
    'WRONG (criteria are lost): {"name": "...", "field": "combination", '
    '"operator": "PRESENT", "value": {"substance": ["22165008"]}}\n\n'
    "RULES\n"
    "- NEVER invent ids (sctid, idDrug, class, examType...). Always resolve "
    "them with the tools. If a lookup returns nothing, say so and ask the "
    "user to refine.\n"
    "- For exam criteria, ALWAYS check list_reference_exams first and use "
    "exam_ref; only fall back to exam (list_exam_types) when the exam is "
    "not available as a reference exam.\n"
    "- Ask ONE focused question at a time while information is missing "
    "(protocol intent, which drugs/exams, thresholds, alert level/texts).\n"
    "- When you have enough information, build the full proposal and call "
    "validate_protocol before presenting it; fix any reported errors first.\n"
    "- Use test_protocol when the user wants to see the rule against "
    "real prescriptions.\n"
    "- Trigger: use ONLY declared variable names; keep it as simple as "
    "possible.\n"
    "- Set proposal to null when the turn is only a question or explanation.\n"
    "- The message field is always short, clear Brazilian Portuguese, written "
    "as simple HTML because it is rendered directly in the chat. Use ONLY "
    "these tags: <p>, <br>, <strong>, <em>, <ul>, <ol>, <li>, <code>, and "
    "wrap every paragraph in <p>. NEVER use Markdown — no **bold**, no # "
    "headings, no - bullets, no ``` code fences. Never emit <a>, <img>, "
    "headings, tables, or any tag attribute: they are stripped before "
    "rendering and the user loses the formatting."
)


@has_permission(Permission.WRITE_PROTOCOLS)
def chat(request_data: ProtocolAgentChatRequest, user_context: User):
    """Run one co-pilot chat turn and gate any proposal behind validation."""
    turn = _run_agent_turn(request_data=request_data, user_context=user_context)

    message = str(turn.message or "").strip()[:MAX_MESSAGE_LENGTH]
    proposal = turn.proposal.model_dump() if turn.proposal else None
    proposal_errors = []

    if proposal is not None:
        proposal["config"] = _normalize_config(config=proposal.get("config"))
        proposal_errors = _validate_proposal(
            proposal=proposal, draft=request_data.draft.model_dump()
        )
        if proposal_errors:
            proposal = None

    return {
        "message": message,
        "proposal": proposal,
        "proposalErrors": proposal_errors,
    }


def _run_agent_turn(
    request_data: ProtocolAgentChatRequest, user_context: User
) -> ProtocolAgentTurnOutput:
    """Replay the transcript and run one bounded Strands agent turn."""
    bedrock_model = BedrockModel(
        model_id=Config.PROTOCOL_AGENT_MODEL_ID,
        region_name=Config.PROTOCOL_AGENT_REGION,
        boto_client_config=BotoConfig(read_timeout=BEDROCK_READ_TIMEOUT),
    )

    agent = Agent(
        model=bedrock_model,
        tools=build_tools(
            schema=user_context.schema,
            validate_config=_validate_config,
            normalize_config=_normalize_config,
        ),
        system_prompt=AGENT_SYSTEM_PROMPT,
        messages=_to_strands_messages(request_data=request_data),
        callback_handler=None,
        tool_executor=SequentialToolExecutor(),
    )

    try:
        result = agent(
            _turn_prompt(request_data=request_data),
            structured_output_model=ProtocolAgentTurnOutput,
            limits=Limits(turns=Config.PROTOCOL_AGENT_MAX_TURNS),
        )
    except ReadTimeoutError:
        logger.backend_logger.warning("Protocol agent: bedrock read timeout")
        _raise_unavailable()
    except Exception as error:
        logger.backend_logger.error("Protocol agent failure: %s", str(error)[:1000])
        _raise_unavailable()

    if result.stop_reason == "guardrail_intervened":
        logger.backend_logger.warning("Protocol agent: guardrail intervened")
        _raise_unavailable()

    output = getattr(result, "structured_output", None)
    if isinstance(output, ProtocolAgentTurnOutput):
        return output

    if result.stop_reason == "limit_turns":
        return ProtocolAgentTurnOutput(message=LIMIT_TURNS_MESSAGE, proposal=None)

    logger.backend_logger.error(
        "Protocol agent: missing structured output (stop_reason=%s)",
        result.stop_reason,
    )
    _raise_unavailable()


def _to_strands_messages(request_data: ProtocolAgentChatRequest) -> list:
    """Convert the frontend-held transcript to Strands/Bedrock message format."""
    return [
        {"role": m.role, "content": [{"text": m.content}]}
        for m in request_data.messages
    ]


def _turn_prompt(request_data: ProtocolAgentChatRequest) -> str:
    """Build the turn prompt with the current form draft and the new message."""
    draft_json = json.dumps(
        request_data.draft.model_dump(), ensure_ascii=False, default=str
    )

    return (
        f"<rascunho_atual>{draft_json}</rascunho_atual>\n"
        f"<mensagem_usuario>{request_data.message}</mensagem_usuario>"
    )


def _validate_config(config: dict, protocol_type: int) -> list[str]:
    """Validate an unsaved config (adapter used by the validate_protocol tool)."""
    return _validate_proposal(
        proposal={"protocolType": protocol_type, "config": _normalize_config(config)},
        draft={},
    )


def _normalize_config(config: dict) -> dict:
    """Return the config with every variable in the shape the system expects."""
    if not isinstance(config, dict):
        return config

    variables = config.get("variables")
    if not isinstance(variables, list):
        return config

    return {
        **config,
        "variables": [_normalize_variable(variable=v) for v in variables],
    }


def _normalize_variable(variable: dict) -> dict:
    """Flatten a combination variable whose criteria came wrapped in an object.

    The model tends to answer with {"operator": "PRESENT", "value": {...}} for
    combination variables. Neither key exists for this field, so the criteria
    have to be lifted to the variable itself; an already flat criterion always
    wins over the nested one.
    """
    if not isinstance(variable, dict):
        return variable

    if variable.get("field") != ProtocolVariableFieldEnum.COMBINATION.value:
        return variable

    normalized = dict(variable)
    nested_criteria = {}

    for key in COMBINATION_NESTED_KEYS:
        nested = normalized.pop(key, None)
        if isinstance(nested, dict):
            nested_criteria.update(nested)

    normalized.pop("operator", None)

    for key, value in nested_criteria.items():
        if key in COMBINATION_CRITERIA_FIELDS and normalized.get(key) is None:
            normalized[key] = value

    return normalized


def _validate_proposal(proposal: dict, draft: dict) -> list[str]:
    """Validate an agent proposal with the same rules applied on protocol upsert."""
    if not isinstance(proposal, dict):
        return ["Proposta inválida"]

    config = proposal.get("config")
    if not isinstance(config, dict):
        return ["Proposta sem configuração"]

    errors = []

    protocol_type = proposal.get("protocolType") or (draft or {}).get("protocolType")
    if protocol_type not in [item.value for item in ProtocolTypeEnum]:
        return ["Tipo de protocolo inválido ou não informado"]

    variables = config.get("variables") or []
    trigger = str(config.get("trigger") or "").strip()
    result = config.get("result") or {}

    if len(variables) > MAX_PROPOSAL_VARIABLES:
        errors.append("Número de variáveis excede o limite")

    try:
        admin_protocol_service._validate_variables(
            variables=variables, protocol_type=protocol_type
        )
    except ValidationError as error:
        errors.append(str(error))

    errors.extend(_combination_criteria_errors(variables=variables))

    if not trigger:
        errors.append("Gatilho não informado")
    elif len(trigger) > MAX_TRIGGER_LENGTH:
        errors.append("Gatilho excede o tamanho máximo")
    elif not _is_valid_trigger(
        trigger=trigger,
        variable_names=[str(v.get("name")) for v in variables if isinstance(v, dict)],
    ):
        errors.append("Gatilho possui formato inválido")

    if not isinstance(result, dict) or not str(result.get("message") or "").strip():
        errors.append("Mensagem de alerta não informada")
    if isinstance(result, dict) and result.get("level") not in RESULT_LEVELS:
        errors.append("Nível de alerta inválido")

    if not errors:
        try:
            admin_protocol_service._test_protocol(
                protocol={
                    "variables": variables,
                    "trigger": trigger,
                    "result": result,
                }
            )
        except ValidationError as error:
            errors.append(str(error))

    return errors


def _combination_criteria_errors(variables: list) -> list[str]:
    """Reject combination variables with no criteria at all.

    Upsert tolerates them (it only drops the empty attributes), but a criteria-less
    combo matches every prescription item, so an agent proposal must never carry
    one — usually the sign of criteria the model put in the wrong place.
    """
    errors = []

    for variable in variables:
        if not isinstance(variable, dict):
            continue

        if variable.get("field") != ProtocolVariableFieldEnum.COMBINATION.value:
            continue

        has_criteria = any(
            variable.get(field) is not None and variable.get(field) != []
            for field in COMBINATION_CRITERIA_FIELDS
        )

        if not has_criteria:
            errors.append(
                f"Variável {variable.get('name')}: COMBO sem nenhum critério "
                "preenchido"
            )

    return errors


def _is_valid_trigger(trigger: str, variable_names: list[str]) -> bool:
    """Check a trigger only references known variables with safe boolean syntax."""
    substituted = trigger
    for name in variable_names:
        substituted = substituted.replace("{{" + name + "}}", "True")

    if not re.match(SAFE_LOGICAL_EXPR_REGEX, substituted):
        return False

    try:
        compile(substituted, "<trigger>", "eval")
    except SyntaxError:
        return False

    return True


def _raise_unavailable():
    raise ValidationError(
        "Serviço de IA indisponível",
        "errors.serviceUnavailable",
        status.HTTP_503_SERVICE_UNAVAILABLE,
    )
