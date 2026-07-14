"""Service: get custom reports"""

import json
from datetime import datetime, timedelta
from typing import Union

from config import Config
from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import Report
from models.enums import ReportStatusEnum
from models.main import User
from models.requests.reports_custom_request import SuggestGraphsRequest
from repository.reports import reports_repository
from services.reports import reports_cache_service
from utils import aws, dateutils, logger, status, stringutils

CHART_SUGGESTION_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
CHART_SUGGESTION_MAX_TOKENS = 2048
MAX_SUGGESTIONS = 4

CHART_SUGGESTION_EXAMPLES = (
    '[{"type": "hbar", "title": "Incidência por Germe", '
    '"xKeys": ["microorganismo_agrupado"], "yKeys": ["germe_unico"], '
    '"aggregation": "sum", "sortOrder": "desc", "width": "full"}, '
    '{"type": "hbar", "title": "Perfil de Sensibilidade - Klebsiella pneumoniae", '
    '"xKeys": ["nomemedicamento"], "yKeys": ["Sensivel/I", "Resistente"], '
    '"aggregation": "sum", "stacked": true, "width": "full"}, '
    '{"type": "line", "title": "Evolução Mensal de Atendimentos", '
    '"xKeys": ["data_atendimento"], "yKeys": [], '
    '"aggregation": "count", "dateGrouping": "month", "width": "full"}]'
)

_VALID_CHART_TYPES = {"bar", "hbar", "line", "pie"}
_VALID_AGGREGATIONS = {"none", "count", "count_pct", "sum", "avg", "min", "max"}
_NUMERIC_AGGREGATIONS = {"sum", "avg", "min", "max"}
_VALID_DATE_GROUPINGS = {"none", "day", "week", "month", "quarter", "year"}
_VALID_SORT_ORDERS = {"none", "asc", "desc"}
_ALLOWED_CHART_FIELDS = {
    "type",
    "title",
    "xKeys",
    "yKeys",
    "aggregation",
    "width",
    "dateGrouping",
    "topN",
    "sortOrder",
    "stacked",
}


@has_permission(Permission.READ_REPORTS)
def get_report_list(user_context: User, user_permissions: list[Permission]):
    """Get list of custom reports."""
    custom_reports_query_result = reports_repository.get_custom_reports(
        all=Permission.READ_CUSTOM_REPORTS in user_permissions
    )
    custom_reports = []
    for report in custom_reports_query_result:
        custom_reports.append(
            {
                "id": report.id,
                "name": report.name,
                "description": report.description,
                "active": report.active,
                "status": report.status,
                "processed_at": dateutils.to_iso(report.processed_at),
                "available_reports": reports_cache_service.list_available_custom_reports(
                    schema=user_context.schema, id_report=report.id
                ),
                "error_message": report.error
                if Permission.READ_CUSTOM_REPORTS in user_permissions
                else None,
            }
        )

    return custom_reports


@has_permission(Permission.READ_REPORTS)
def get_report_link(
    id_report: int,
    user_context: User,
    user_permissions: list[Permission],
    filename: Union[str, None] = None,
):
    """Get custom report presigned link."""
    report_data = reports_repository.get_report(id_report=id_report)

    _validate_report(
        report_data=report_data,
        user_context=user_context,
        user_permissions=user_permissions,
    )

    if filename is None:
        filename = f"{datetime.now().strftime('%Y%m%d')}.csv.gz"

    cached_link = reports_cache_service.generate_link(
        resource_path=_get_resource_path(
            id_report=id_report, schema=user_context.schema, filename=filename
        )
    )

    if not cached_link:
        return {"cached": False}

    return {
        "cached": True,
        "title": report_data.name,
        "url": cached_link,
        "graphs": report_data.graphs,
    }


@has_permission(Permission.READ_REPORTS)
def process_report(
    id_report: int, user_context: User, user_permissions: list[Permission]
):
    """Get custom report presigned link."""
    report_data = reports_repository.get_report(id_report=id_report)

    _validate_report(
        report_data=report_data,
        user_context=user_context,
        user_permissions=user_permissions,
    )

    if report_data.status == ReportStatusEnum.PROCESSING.value:
        raise ValidationError(
            "Relatório já está sendo processado",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    if (
        report_data.processed_at is not None
        and Permission.READ_CUSTOM_REPORTS not in user_permissions
    ):
        # Allow reprocessing only if processed_at is older than 1 hour
        time_since_processed = datetime.now() - report_data.processed_at
        if time_since_processed < timedelta(hours=1):
            raise ValidationError(
                "Relatório já foi processado recentemente. Aguarde 1 hora para processar novamente.",
                "errors.invalidRecord",
                status.HTTP_400_BAD_REQUEST,
            )

    payload = {
        "command": "lambda_custom_reports.process_custom_report",
        "id_user": user_context.id,
        "id_report": id_report,
        "schema": user_context.schema,
    }

    lambda_client = aws.get_client("lambda", region_name=Config.NIFI_SQS_QUEUE_REGION)
    lambda_client.invoke(
        FunctionName=Config.BACKEND_FUNCTION_NAME,
        InvocationType="Event",
        Payload=json.dumps(payload),
    )

    # change report status
    report_data.status = ReportStatusEnum.PROCESSING.value

    return True


def _validate_report(
    report_data: Union[Report, None],
    user_context: User,
    user_permissions: list[Permission],
):
    """Check if the report is viewable."""
    if not report_data:
        raise ValidationError(
            "Relatório inválido",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    if Permission.WRITE_CUSTOM_REPORTS in user_permissions:
        return True

    if report_data.active is False:
        raise ValidationError(
            "Relatório não está ativo",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    # user_context is already a User object, no need to query again
    ignored_reports = (
        user_context.reports_config.get("ignore", [])
        if user_context.reports_config
        else []
    )

    if "CUSTOM" in ignored_reports:
        raise ValidationError(
            "Usuário não possui permissão neste recurso",
            "errors.invalidPermission",
            status.HTTP_401_UNAUTHORIZED,
        )

    return True


@has_permission(Permission.WRITE_CUSTOM_REPORTS_GRAPHS)
def suggest_graphs(request_data: SuggestGraphsRequest) -> list[dict]:
    """Ask Bedrock Claude Sonnet to suggest chart configurations for the report data."""
    columns_json = json.dumps(
        [
            {
                "key": c.key,
                "label": c.label,
                "type": c.type,
                "options": c.options[:20] if c.options else None,
                "distinctCount": c.distinctCount,
            }
            for c in request_data.columns
        ],
        ensure_ascii=False,
    )
    rows_json = json.dumps(
        _truncate_rows(request_data.sampleRows), ensure_ascii=False
    )
    existing_titles_json = json.dumps(request_data.existingTitles, ensure_ascii=False)

    user_message = (
        f"Column schema:\n{columns_json}\n\n"
        f"Sample rows (values may be truncated):\n{rows_json}\n\n"
        f"Existing chart titles (do not duplicate): {existing_titles_json}\n\n"
        f"User hint: {request_data.hint or '(none)'}"
    )

    system = (
        "You are a data-visualization assistant embedded in NoHarm, a clinical "
        "pharmacy analytics tool. You receive the column schema and a few sample "
        "rows of a tabular report and must propose up to 4 chart configurations "
        "that give the most useful insight into the data.\n\n"
        "Respond ONLY with a valid, compact JSON array of chart objects — no "
        "explanation, no markdown fences, no trailing text.\n\n"
        "Each chart object may contain ONLY these fields:\n"
        '- "type": "bar" | "hbar" | "line" | "pie" (required)\n'
        '- "title": short descriptive title in Brazilian Portuguese (required)\n'
        '- "xKeys": array with exactly 1 column key from the schema (required)\n'
        '- "yKeys": array of column keys from the schema. Rules:\n'
        '  * if "aggregation" is "count" or "count_pct", yKeys MUST be []\n'
        '  * if "aggregation" is "sum", "avg", "min" or "max", every yKey MUST be a '
        'column of type "number"\n'
        '  * "pie" charts use at most 1 yKey\n'
        '- "aggregation": "none" | "count" | "count_pct" | "sum" | "avg" | "min" | '
        '"max" (required)\n'
        '- "width": "full" | "half" (default "half"; use "full" for line charts '
        "over time)\n"
        '- "dateGrouping": "none" | "day" | "week" | "month" | "quarter" | "year" — '
        'only when the xKey is a "date" column; pick a granularity that yields '
        "roughly 5-30 points\n"
        '- "topN": integer — use 10 when the x column has many distinct values '
        "(see distinctCount); otherwise omit\n"
        '- "sortOrder": "none" | "asc" | "desc" — sort by value; use "desc" '
        "together with topN\n"
        '- "stacked": boolean — only for bar/hbar with 2+ yKeys or when comparing '
        "categories\n\n"
        "Guidelines:\n"
        "- Use ONLY column keys present in the schema. Never invent keys.\n"
        '- Good patterns: low-cardinality string column + "count" -> bar or pie; '
        'date column + "count" or "sum" -> line with dateGrouping; '
        'numeric metric by category -> hbar with "sum"/"avg", sortOrder "desc", '
        "topN 10.\n"
        "- Avoid identifier-like columns (very high distinctCount, codes, ids, "
        "person names) as pie/bar dimensions.\n"
        "- When the data contains 0/1 indicator columns or pre-aggregated numeric "
        'columns, prefer "sum" over those columns instead of "count" of rows.\n'
        "- When two complementary numeric columns exist (e.g. sensível/resistente, "
        "positivo/negativo), suggest a stacked hbar comparing them.\n"
        '- Title style: short Brazilian Portuguese noun phrases like "Incidência '
        'por X" or "Perfil de Y - Z".\n'
        "- Do not repeat any of the existing chart titles.\n"
        "- If the user provides a hint, treat it as the top priority.\n"
        "- Return between 1 and 4 charts. If no meaningful chart is possible, "
        "return [].\n\n"
        "Examples of well-made charts from OTHER reports (style reference ONLY — "
        "their column keys do NOT exist in this dataset, never reuse them):\n"
        f"{CHART_SUGGESTION_EXAMPLES}"
    )

    messages = [{"role": "user", "content": user_message}]
    parsed = _prompt_sonnet(messages=messages, system=system)

    return _sanitize_suggestions(parsed, request_data)


def _truncate_rows(rows: list[dict], max_len: int = 120) -> list[dict]:
    """Truncate long string values in sample rows before sending them to the LLM."""
    truncated = []
    for row in rows:
        truncated_row = {}
        for key, value in row.items():
            if isinstance(value, str) and len(value) > max_len:
                truncated_row[key] = value[:max_len]
            else:
                truncated_row[key] = value
        truncated.append(truncated_row)
    return truncated


def _sanitize_suggestions(
    parsed, request_data: SuggestGraphsRequest
) -> list[dict]:
    """Validate and clean LLM-suggested chart configs, dropping anything invalid."""
    if isinstance(parsed, dict):
        parsed = parsed.get("charts", [])

    if not isinstance(parsed, list):
        raise ValidationError(
            "Resposta inválida do serviço de IA",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    valid_keys = {c.key for c in request_data.columns}
    numeric_keys = {c.key for c in request_data.columns if c.type == "number"}
    date_keys = {c.key for c in request_data.columns if c.type == "date"}

    suggestions = []
    for item in parsed:
        if not isinstance(item, dict):
            continue

        chart = {k: v for k, v in item.items() if k in _ALLOWED_CHART_FIELDS}

        chart_type = chart.get("type")
        if chart_type not in _VALID_CHART_TYPES:
            continue

        aggregation = chart.get("aggregation")
        if aggregation not in _VALID_AGGREGATIONS:
            continue

        title = chart.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        chart["title"] = title.strip()[:120]

        x_keys = chart.get("xKeys")
        if not isinstance(x_keys, list):
            continue
        x_keys = [k for k in x_keys if k in valid_keys][:1]
        if not x_keys:
            continue
        chart["xKeys"] = x_keys

        y_keys = chart.get("yKeys") if isinstance(chart.get("yKeys"), list) else []
        y_keys = [k for k in y_keys if k in valid_keys]

        if aggregation in ("count", "count_pct"):
            y_keys = []
        elif aggregation in _NUMERIC_AGGREGATIONS:
            y_keys = [k for k in y_keys if k in numeric_keys]
            if not y_keys:
                continue
        chart["yKeys"] = y_keys[:1] if chart_type == "pie" else y_keys

        date_grouping = chart.get("dateGrouping")
        if x_keys[0] not in date_keys or date_grouping not in _VALID_DATE_GROUPINGS:
            chart.pop("dateGrouping", None)

        sort_order = chart.get("sortOrder")
        if sort_order not in _VALID_SORT_ORDERS:
            chart.pop("sortOrder", None)

        if chart.get("width") not in ("full", "half"):
            chart["width"] = "half"

        top_n = chart.get("topN")
        if not isinstance(top_n, int) or top_n < 0:
            chart.pop("topN", None)

        if not isinstance(chart.get("stacked"), bool):
            chart.pop("stacked", None)

        suggestions.append(chart)

        if len(suggestions) >= MAX_SUGGESTIONS:
            break

    return suggestions


def _parse_llm_json(raw: str) -> list:
    """Strip markdown fences from raw LLM output and parse as JSON."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, KeyError) as error:
        logger.backend_logger.error("Resposta inválida do serviço de IA: %s", error)
        raise ValidationError(
            "Resposta inválida do serviço de IA",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )


def _prompt_sonnet(messages: list, system: str) -> list:
    """Invoke Bedrock Claude Sonnet and return the parsed JSON response."""
    client = aws.get_client("bedrock-runtime", region_name="us-east-1")

    body = json.dumps(
        {
            "max_tokens": CHART_SUGGESTION_MAX_TOKENS,
            "system": system,
            "messages": messages,
            "anthropic_version": "bedrock-2023-05-31",
        }
    )

    try:
        response = client.invoke_model(
            body=body,
            modelId=CHART_SUGGESTION_MODEL_ID,
            accept="application/json",
            contentType="application/json",
        )
    except Exception as error:
        logger.backend_logger.error("Serviço de IA indisponível: %s", error)
        raise ValidationError(
            "Serviço de IA indisponível",
            "errors.serviceUnavailable",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    response_body = json.loads(response.get("body").read())
    return _parse_llm_json(response_body["content"][0]["text"])


def _get_resource_path(id_report: int, schema: str, filename: str):
    """Get resource path for custom report."""

    resource_path = f"reports/{schema}/CUSTOM/{id_report}/{filename}"

    if not stringutils.is_valid_filename(
        resource_path=resource_path, valid_extensions={".csv", ".xlsx", ".json.gz"}
    ):
        raise ValidationError(
            "Nome de arquivo inválido",
            "errors.invalidFilename",
            status.HTTP_400_BAD_REQUEST,
        )

    return resource_path
