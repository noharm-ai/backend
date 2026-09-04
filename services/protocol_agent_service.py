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
from repository import exams_repository
from services import clinical_notes_service
from services.admin import admin_protocol_service
from services.protocol_agent_tools import build_tools
from utils import logger, status
from utils.alert_protocol import SAFE_LOGICAL_EXPR_REGEX

BEDROCK_READ_TIMEOUT = 20
MAX_MESSAGE_LENGTH = 4000
MAX_PROPOSAL_VARIABLES = 50
MAX_TRIGGER_LENGTH = 500
RESULT_LEVELS = {"low", "medium", "high"}

# Exam keys that are valid at runtime but never appear in the exam type catalog:
# the creatinina exam is stored under "cr" instead of its own type, and these
# three are merged in as extra keys derived from the exam initials.
EXAM_TYPE_ALIASES = {"cr", "tgo", "tgp", "plqt"}

# Fields where the model tends to invent an impossible value to mean "absent".
# No real threshold reaches -999, so anything at or below it is a sentinel.
SENTINEL_CHECKED_FIELDS = {
    ProtocolVariableFieldEnum.EXAM.value,
    ProtocolVariableFieldEnum.EXAM_REF.value,
    ProtocolVariableFieldEnum.CN_STATS.value,
}
SENTINEL_VALUE_THRESHOLD = -999

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
    "drugAlertLimit",
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
    "calls. Write the operators in LOWER CASE. Maximum 500 characters.\n"
    '- config.result: {"type": "SHOW_MESSAGE", "level": "low"|"medium"|"high", '
    '"message": "<short alert>", "description": "<longer explanation>"}.\n'
    "- config.onlyLatestExpireDate (optional, default false): an aggregated "
    "prescription is evaluated once per expire date group of its items, and it "
    "also carries items prescribed on previous days; the protocol always runs "
    "on every group, but setting it to true makes the alert count in the "
    "prescription summary only when it fires on a group holding items "
    "prescribed on the current prescription date; for a PRESCRIPTION_ITEM "
    "protocol, the item that matched the combination is the one whose "
    "prescription date must be the current one.\n\n"
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
    "(search_reference_exams: copy the tpexam field VERBATIM, including case); "
    "optional examRefPeriod (max age of the exam, in days). Prefer an exam with "
    "configuredInThisHospital=true. PREFERRED field for exam-based criteria.\n"
    "- exam → > < >= <= = != → number; requires examType, always lower case "
    "(search_exam_types); optional examPeriod. Fallback only: use exam_ref "
    "instead whenever the exam exists in search_reference_exams.\n"
    "- age, weight, admissionTime (hours since admission), stConcilia → "
    "> < >= <= = != → number.\n"
    "- imc → > < >= <= = != → number. Body mass index in kg/m², computed "
    "automatically as weight / (height/100)² from the patient's registered "
    "weight (kg) and height (cm). Do NOT create a combination of weight and "
    "height variables to express BMI, and do NOT ask the user for the "
    "formula — use this field. Evaluates to false when either weight or "
    "height is missing. There is no standalone height field.\n"
    "- cn_stats → > < >= <= = != → number; requires statsType "
    "(list_stats_types).\n"
    "- dischargeReason, insurance → CONTAINS → text.\n"
    "- segmentType → IN/NOTIN → list.\n"
    "- tags → IN/NOTIN → list of patient tag names (list_tags). Tested "
    "against the tags (marcadores) assigned to the patient; a patient without "
    "tags never matches IN and always matches NOTIN.\n"
    "- combination (only for protocolType 4): per-item criteria. True when ANY "
    "prescription item matches ALL the filled criteria. This field has NO "
    "operator and NO value: every criterion is a FLAT key of the variable "
    "itself. NEVER nest them inside an object. Available criteria: substance "
    "(list of sctid), class (list), drug (list of idDrug), route (list of "
    "route ids from list_routes, compared verbatim against the route of the "
    "prescribed item — copy the id exactly, including case), drugAttribute "
    "(list of: mav = alta vigilância, antimicro, controlled, dialyzable, "
    "elderly = inapropriado para idosos, notdefault = não padronizado, "
    "chemo = quimioterápico; no other value exists), drugAlertLimit "
    "(list of: kidney = possui valor limite nefrotóxico, liver = possui valor "
    "limite hepático, not_kidney = não possui valor limite nefrotóxico, "
    "not_liver = não possui valor limite hepático; no other value exists — "
    "never write renal, nefrotoxico or hepatico. Tests whether the drug has a "
    "nephro/hepatotoxicity alert threshold configured in medatributos "
    "renal/hepatico; a blank or zero threshold counts as 'não possui'. Matches "
    "when the item satisfies ANY of the selected options), intravenous "
    "(true/false), feedingTube (true/false), dose + doseOperator, "
    "defaultMeasureUnit (mg|ml|mcg|UI, the unit the dose is expressed in), "
    "frequencyday + frequencydayOperator, period + periodOperator, "
    "observation (free text). Correct shape:\n"
    '{"name": "dipirona_dose_alta", "field": "combination", '
    '"substance": ["22165008"], "route": ["ORAL"], "dose": 200, '
    '"doseOperator": ">", "defaultMeasureUnit": "mg"}\n'
    'WRONG (criteria are lost): {"name": "...", "field": "combination", '
    '"operator": "PRESENT", "value": {"substance": ["22165008"]}}\n\n'
    "ABSENCE OF DATA (exam, exam_ref, cn_stats)\n"
    "When the user asks about the ABSENCE of an exam or indicator — 'paciente "
    "sem creatinina', 'não tem hemograma', 'nenhum exame de função renal' — "
    "there is NO value that means absent. NEVER invent an impossible number "
    "like -999 to represent it: no such row exists in the database, so the "
    "comparison is simply never true and the protocol never fires.\n"
    "The pattern is: declare the variable POSITIVELY with operator '>' and "
    "value 0, which is true whenever any result of that type exists, and negate "
    "it in the TRIGGER with 'not'. A variable is false when the patient has no "
    "result, so its negation is exactly 'the patient has no such exam'.\n"
    'CORRECT — variable {"name": "tem_creatinina", "field": "exam_ref", '
    '"examRefType": "<tpexam>", "operator": ">", "value": 0} '
    'with trigger "not {{tem_creatinina}}".\n'
    'WRONG (never matches): {"name": "sem_creatinina", "field": "exam_ref", '
    '"examRefType": "<tpexam>", "operator": "=", "value": -999} '
    'with trigger "{{sem_creatinina}}".\n'
    "Name the variable after what it detects when TRUE (tem_..., possui_...), "
    "because the trigger is what inverts it. Combine it freely with other "
    "variables, e.g. \"{{idoso}} and not {{tem_creatinina}}\".\n"
    "This trick is ONLY for the numeric fields (exam, exam_ref, cn_stats), which "
    "have no negative operator. For list fields (substance, class, idDrug, "
    "route, idDepartment, idSegment, idIcd, tags) use the NOTIN operator directly on "
    "the variable and do NOT negate the trigger.\n\n"
    "RULES\n"
    "- NEVER invent ids (sctid, idDrug, class, examType, examRefType, "
    "statsType...). Only ever write an id you read from a tool result in this "
    "conversation, and NEVER derive one from the name of the exam. If a lookup "
    "returns nothing, say so and ask the user to refine.\n"
    "- Catalog listings return {items, returned, total, truncated}. When "
    "truncated is true the list is INCOMPLETE: call the tool again with a "
    "narrower search term. Never pick an id from a truncated list and never "
    "guess the one you were looking for.\n"
    "- When a tool returns an error, tell the user the lookup failed and stop; "
    "never continue with an id you could not resolve.\n"
    "- For exam criteria, ALWAYS check search_reference_exams first and use "
    "exam_ref; only fall back to exam (search_exam_types) when the exam is "
    "not available as a reference exam.\n"
    "- Ask ONE focused question at a time while information is missing "
    "(protocol intent, which drugs/exams, thresholds, alert level/texts).\n"
    "- When you have enough information, build the full proposal and call "
    "validate_protocol. You MUST get valid=true before presenting a proposal; "
    "fix every reported error first. If it reports an exam or indicator that "
    "does not exist, search again with the proper tool and correct the id — "
    "never present a proposal that failed validation.\n"
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

    # examType is keyed in lower case at runtime, so a model that answers with
    # the exam name in upper case still resolves. examRefType is deliberately
    # left alone: it is matched verbatim, so lowercasing would break valid ids.
    if variable.get("field") == ProtocolVariableFieldEnum.EXAM.value:
        exam_type = variable.get("examType")
        if isinstance(exam_type, str):
            return {**variable, "examType": exam_type.strip().lower()}
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


def _sentinel_value_errors(variables: list) -> list[str]:
    """Reject an impossible value used to mean "the patient has no such result".

    No row in the database carries a sentinel, so the comparison never matches
    and the protocol silently never fires. Absence is expressed by declaring the
    variable positively (operator '>' value 0, true when any result exists) and
    negating it in the trigger with 'not'.
    """
    errors = []

    for variable in variables:
        if not isinstance(variable, dict):
            continue

        if variable.get("field") not in SENTINEL_CHECKED_FIELDS:
            continue

        try:
            value = float(variable.get("value"))
        except (TypeError, ValueError):
            continue

        if value <= SENTINEL_VALUE_THRESHOLD:
            errors.append(
                f"Variável {variable.get('name')}: valor {variable.get('value')} não "
                "existe na base. Para detectar a ausência do resultado, declare a "
                'variável com operator ">" e value 0 e negue no gatilho com "not '
                '{{nome_da_variavel}}"'
            )

    return errors


def _load_exam_catalogs(variables: list) -> dict:
    """Load the catalogs needed to check the ids used by these variables.

    Returns a dict with an entry per catalog, or None for a catalog that could
    not be loaded. The check is skipped for a catalog that is None: a database
    hiccup must not block every proposal, and the missing check is logged.
    """
    fields = {v.get("field") for v in variables if isinstance(v, dict)}
    catalogs = {"exam": None, "exam_ref": None, "stats": None}

    # No catalog read at all when nothing references one.
    if ProtocolVariableFieldEnum.EXAM.value in fields:
        try:
            catalogs["exam"] = {
                str(r.typeExam).strip().lower()
                for r in exams_repository.get_exam_types()
            } | EXAM_TYPE_ALIASES
        except Exception as error:
            logger.backend_logger.warning(
                "Protocol agent: exam type catalog unavailable: %s", str(error)[:300]
            )

    if ProtocolVariableFieldEnum.EXAM_REF.value in fields:
        try:
            catalogs["exam_ref"] = {
                str(e.tp_exam).strip().lower(): e.tp_exam
                for e in exams_repository.get_global_exams()
            }
        except Exception as error:
            logger.backend_logger.warning(
                "Protocol agent: reference exam catalog unavailable: %s",
                str(error)[:300],
            )

    if ProtocolVariableFieldEnum.CN_STATS.value in fields:
        try:
            catalogs["stats"] = {
                tag["key"] for tag in clinical_notes_service.get_tags()
            }
        except Exception as error:
            logger.backend_logger.warning(
                "Protocol agent: stats catalog unavailable: %s", str(error)[:300]
            )

    return catalogs


def _catalog_errors(variables: list, catalogs: dict) -> list[str]:
    """Reject ids the agent invented instead of resolving with its tools.

    An id that is not in the catalog never matches at runtime: the protocol is
    silently never activated and the trace blames the patient for not having the
    exam. Rejecting it here surfaces the mistake to the agent through the
    validate_protocol tool, inside the turn, so it can search again and correct
    before the user ever sees the proposal.
    """
    errors = []
    exam_types = catalogs.get("exam")
    exam_refs = catalogs.get("exam_ref")
    stats_types = catalogs.get("stats")

    for variable in variables:
        if not isinstance(variable, dict):
            continue

        field = variable.get("field")
        name = variable.get("name")

        if field == ProtocolVariableFieldEnum.EXAM.value and exam_types is not None:
            exam_type = variable.get("examType")
            # a missing examType is already rejected by _validate_variables
            if exam_type and str(exam_type).strip().lower() not in exam_types:
                errors.append(
                    f"Variável {name}: tipo de exame '{exam_type}' não existe neste "
                    "hospital (use search_exam_types para localizar o examType correto)"
                )

        if field == ProtocolVariableFieldEnum.EXAM_REF.value and exam_refs is not None:
            exam_ref = variable.get("examRefType")
            if not exam_ref:
                errors.append(f"Variável {name}: exame de referência não informado")
            elif exam_ref not in exam_refs.values():
                canonical = exam_refs.get(str(exam_ref).strip().lower())
                if canonical:
                    # only the case is wrong: exam_ref is matched verbatim at
                    # runtime, so name the exact spelling instead of guessing
                    errors.append(
                        f"Variável {name}: exame de referência '{exam_ref}' deve ser "
                        f"escrito exatamente como '{canonical}'"
                    )
                else:
                    errors.append(
                        f"Variável {name}: exame de referência '{exam_ref}' não existe "
                        "no catálogo (use search_reference_exams para localizar o "
                        "tpexam correto)"
                    )

        if (
            field == ProtocolVariableFieldEnum.CN_STATS.value
            and stats_types is not None
        ):
            stats_type = variable.get("statsType")
            if stats_type and stats_type not in stats_types:
                errors.append(
                    f"Variável {name}: indicador NoHarm Care '{stats_type}' não existe "
                    "(use list_stats_types para localizar o statsType correto)"
                )

    return errors


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
    errors.extend(_sentinel_value_errors(variables=variables))
    errors.extend(
        _catalog_errors(
            variables=variables, catalogs=_load_exam_catalogs(variables=variables)
        )
    )

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
