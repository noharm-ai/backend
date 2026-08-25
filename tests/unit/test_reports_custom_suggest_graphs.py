"""Tests: the AI chart-suggestion feature of services/reports/reports_custom_service.py

``suggest_graphs`` asks a Bedrock model for one chart configuration for a custom
report and then hands the answer to a sanitizer before it ever reaches the
client. The model is free-form text, so the sanitizer is the only thing standing
between a hallucinated column key (or an outright malformed answer) and a chart
the frontend cannot render. These tests pin that contract down: what survives
sanitization, what is silently dropped, and what is rejected outright.

Nothing here talks to Bedrock. The service reaches it through
``aws.get_client``, which is replaced, and the ``@has_permission`` gate on
``suggest_graphs`` is bypassed via ``__wrapped__`` so the business logic can be
called without a request context.
"""

import json
from unittest.mock import MagicMock

import pytest

from exception.validation_error import ValidationError
from models.requests.reports_custom_request import (
    SuggestGraphsColumn,
    SuggestGraphsRequest,
)
from services.reports import reports_custom_service
from utils import status

_suggest_graphs = reports_custom_service.suggest_graphs.__wrapped__

# A column schema that covers every type branch the sanitizer cares about: the
# string column is a valid dimension, "valor" the only valid numeric yKey, and
# "data" the only column that may carry a dateGrouping.
COLUMNS = [
    {"key": "setor", "label": "Setor", "type": "string", "distinctCount": 4},
    {"key": "valor", "label": "Valor", "type": "number"},
    {"key": "data", "label": "Data", "type": "date"},
    {"key": "aceito", "label": "Aceito", "type": "string"},
]

ROWS = [{"setor": "UTI", "valor": 3, "data": "2026-01-01", "aceito": "1"}]


def _request(columns=None, rows=None, hint=None, existing_titles=None):
    """Build a SuggestGraphsRequest around the shared column schema."""
    return SuggestGraphsRequest(
        columns=[SuggestGraphsColumn(**c) for c in (columns or COLUMNS)],
        sampleRows=rows or ROWS,
        hint=hint,
        existingTitles=existing_titles or [],
    )


def _chart(**overrides):
    """A chart config that passes sanitization untouched, plus any overrides."""
    chart = {
        "type": "bar",
        "title": "Atendimentos por Setor",
        "xKeys": ["setor"],
        "yKeys": [],
        "aggregation": "count",
    }
    chart.update(overrides)
    return chart


def _sanitize(parsed, request_data=None):
    return reports_custom_service._sanitize_suggestions(
        parsed, request_data or _request()
    )


def _bedrock_client(text: str):
    """A stand-in Bedrock client whose model answers with the given text."""
    client = MagicMock()
    client.invoke_model.return_value = {
        "body": MagicMock(
            read=MagicMock(return_value=json.dumps({"content": [{"text": text}]}))
        )
    }
    return client


# ---------------------------------------------------------------------------
# _truncate_rows: sample rows are trimmed before they are spent as prompt tokens
# ---------------------------------------------------------------------------


def test_truncate_rows_cuts_long_strings_to_the_limit():
    """A clinical note pasted into a cell must not blow up the prompt"""
    rows = reports_custom_service._truncate_rows([{"note": "a" * 500}])

    assert rows == [{"note": "a" * 120}]


def test_truncate_rows_keeps_short_strings_intact():
    """Values already within the limit are passed through unchanged"""
    assert reports_custom_service._truncate_rows([{"setor": "UTI"}]) == [
        {"setor": "UTI"}
    ]


def test_truncate_rows_leaves_non_strings_alone():
    """Only strings have a length to trim: numbers, booleans and null pass through"""
    row = {"valor": 12.5, "aceito": True, "cid": None, "n": 3}

    assert reports_custom_service._truncate_rows([row]) == [row]


def test_truncate_rows_honours_a_custom_limit():
    """The limit is a parameter, not a hard-coded 120"""
    assert reports_custom_service._truncate_rows([{"x": "abcdef"}], max_len=3) == [
        {"x": "abc"}
    ]


def test_truncate_rows_preserves_row_order_and_count():
    """Every sample row survives; only values are touched"""
    rows = reports_custom_service._truncate_rows(
        [{"x": "a" * 200}, {"x": "b"}, {"x": "c" * 200}]
    )

    assert [r["x"][0] for r in rows] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# _parse_llm_json: the model likes to wrap its answer in markdown
# ---------------------------------------------------------------------------


def test_parse_llm_json_reads_a_plain_array():
    """The documented happy path: a bare JSON array"""
    assert reports_custom_service._parse_llm_json('[{"type": "bar"}]') == [
        {"type": "bar"}
    ]


def test_parse_llm_json_strips_a_json_fenced_block():
    """```json fences are stripped before parsing"""
    raw = '```json\n[{"type": "pie"}]\n```'

    assert reports_custom_service._parse_llm_json(raw) == [{"type": "pie"}]


def test_parse_llm_json_strips_a_bare_fenced_block():
    """A fence with no language tag is handled too"""
    raw = '```\n[{"type": "line"}]\n```'

    assert reports_custom_service._parse_llm_json(raw) == [{"type": "line"}]


def test_parse_llm_json_ignores_surrounding_whitespace():
    """Leading and trailing whitespace is not a parse error"""
    assert reports_custom_service._parse_llm_json("  \n [] \n ") == []


def test_parse_llm_json_rejects_unparseable_output():
    """Prose instead of JSON is a 400, not a stack trace"""
    with pytest.raises(ValidationError) as exc:
        reports_custom_service._parse_llm_json("Claro! Aqui está o gráfico:")

    assert exc.value.code == "errors.invalidParams"
    assert exc.value.httpStatus == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# _sanitize_series: expression-based metrics
# ---------------------------------------------------------------------------


def test_sanitize_series_rejects_a_non_list():
    """Anything that is not a list carries no series at all"""
    assert reports_custom_service._sanitize_series({"expr": "contagem()"}) == []
    assert reports_custom_service._sanitize_series(None) == []
    assert reports_custom_service._sanitize_series("contagem()") == []


def test_sanitize_series_keeps_expression_and_label():
    """The two fields the frontend evaluates survive, whitespace trimmed"""
    series = reports_custom_service._sanitize_series(
        [{"expr": "  soma(valor) / contagem() * 100  ", "label": "  Taxa  "}]
    )

    assert series == [{"expr": "soma(valor) / contagem() * 100", "label": "Taxa"}]


def test_sanitize_series_drops_entries_without_a_usable_expression():
    """``expr`` is the whole point of a series: no expr, no entry"""
    series = reports_custom_service._sanitize_series(
        [
            "contagem()",  # not an object
            {"label": "Sem formula"},  # missing expr
            {"expr": "   "},  # blank expr
            {"expr": 42},  # non-string expr
            {"expr": "contagem()"},  # the only keeper
        ]
    )

    assert series == [{"expr": "contagem()"}]


def test_sanitize_series_omits_a_blank_or_non_string_label():
    """A label that says nothing is left out rather than kept empty"""
    series = reports_custom_service._sanitize_series(
        [{"expr": "contagem()", "label": "   "}, {"expr": "soma(valor)", "label": 7}]
    )

    assert series == [{"expr": "contagem()"}, {"expr": "soma(valor)"}]


def test_sanitize_series_truncates_long_expressions_and_labels():
    """Length caps keep a runaway answer from reaching the client"""
    series = reports_custom_service._sanitize_series(
        [{"expr": "c" * 900, "label": "L" * 400}]
    )

    assert len(series[0]["expr"]) == 500
    assert len(series[0]["label"]) == 120


def test_sanitize_series_caps_the_number_of_metrics():
    """At most six metrics, however many the model returns"""
    series = reports_custom_service._sanitize_series(
        [{"expr": f"contagem({i})"} for i in range(20)]
    )

    assert len(series) == 6


# ---------------------------------------------------------------------------
# _sanitize_suggestions: shape of the answer
# ---------------------------------------------------------------------------


def test_sanitize_accepts_a_valid_chart_unchanged():
    """A well-formed chart comes back with its fields intact"""
    assert _sanitize([_chart()]) == [_chart(width="half")]


def test_sanitize_unwraps_a_charts_object():
    """The model sometimes answers with {"charts": [...]} instead of an array"""
    assert _sanitize({"charts": [_chart()]}) == [_chart(width="half")]


def test_sanitize_returns_nothing_for_an_empty_answer():
    """ "No meaningful chart is possible" is a legitimate answer"""
    assert _sanitize([]) == []
    assert _sanitize({"charts": []}) == []


def test_sanitize_rejects_an_answer_that_is_not_a_list():
    """A scalar or a foreign object is a broken answer, not an empty one"""
    with pytest.raises(ValidationError) as exc:
        _sanitize("bar")

    assert exc.value.code == "errors.invalidParams"
    assert exc.value.httpStatus == status.HTTP_400_BAD_REQUEST


def test_sanitize_rejects_an_object_without_a_charts_key():
    """An unwrapped object degrades to [], and [] is a valid list"""
    assert _sanitize({"chart": _chart()}) == []


def test_sanitize_skips_non_object_entries():
    """List items that are not objects are dropped, later ones still considered"""
    assert _sanitize(["bar", None, _chart()]) == [_chart(width="half")]


def test_sanitize_caps_the_number_of_suggestions():
    """Only MAX_SUGGESTIONS charts are returned, however many are offered"""
    charts = [_chart(title=f"Grafico {i}") for i in range(5)]

    assert len(_sanitize(charts)) == reports_custom_service.MAX_SUGGESTIONS


def test_sanitize_strips_fields_outside_the_allowed_set():
    """Only the documented chart fields reach the client"""
    result = _sanitize([_chart(sql="select 1", colors=["#fff"], onClick="alert(1)")])

    assert set(result[0]) <= reports_custom_service._ALLOWED_CHART_FIELDS
    assert "sql" not in result[0]


# ---------------------------------------------------------------------------
# _sanitize_suggestions: type, title, aggregation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("chart_type", ["bar", "hbar", "line", "pie"])
def test_sanitize_accepts_every_supported_chart_type(chart_type):
    """The four renderable types all pass"""
    assert _sanitize([_chart(type=chart_type)])[0]["type"] == chart_type


@pytest.mark.parametrize("chart_type", ["scatter", "donut", "", None, 3])
def test_sanitize_drops_an_unrenderable_chart_type(chart_type):
    """A type the frontend cannot draw is discarded"""
    assert _sanitize([_chart(type=chart_type)]) == []


def test_sanitize_drops_an_unknown_aggregation():
    """Aggregations are evaluated by the client, so only known ones survive"""
    assert _sanitize([_chart(aggregation="median")]) == []


def test_sanitize_drops_a_chart_without_a_usable_title():
    """A chart with no title has nothing to show in its header"""
    assert _sanitize([_chart(title="   ")]) == []
    assert _sanitize([_chart(title=None)]) == []


def test_sanitize_trims_and_truncates_the_title():
    """Titles are trimmed and capped so the header stays readable"""
    result = _sanitize([_chart(title="  " + "T" * 400 + "  ")])

    assert len(result[0]["title"]) == 120


# ---------------------------------------------------------------------------
# _sanitize_suggestions: keys must exist in the report's own schema
# ---------------------------------------------------------------------------


def test_sanitize_drops_a_chart_whose_x_key_was_invented():
    """A hallucinated dimension leaves the chart with no x axis at all"""
    assert _sanitize([_chart(xKeys=["nao_existe"])]) == []


def test_sanitize_drops_a_chart_with_no_x_keys():
    """xKeys is required, and a non-list is as good as missing"""
    assert _sanitize([_chart(xKeys=[])]) == []
    assert _sanitize([_chart(xKeys="setor")]) == []


def test_sanitize_keeps_only_the_first_x_key():
    """Exactly one dimension is supported, extras are dropped"""
    result = _sanitize([_chart(xKeys=["setor", "aceito"])])

    assert result[0]["xKeys"] == ["setor"]


def test_sanitize_discards_invented_y_keys():
    """Unknown yKeys are removed while the chart itself survives"""
    result = _sanitize([_chart(aggregation="sum", yKeys=["valor", "nao_existe"])])

    assert result[0]["yKeys"] == ["valor"]


# ---------------------------------------------------------------------------
# _sanitize_suggestions: aggregation / yKeys consistency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("aggregation", ["count", "count_pct"])
def test_sanitize_clears_y_keys_when_counting_rows(aggregation):
    """Counting rows takes no measure column, so yKeys are forced empty"""
    result = _sanitize([_chart(aggregation=aggregation, yKeys=["valor"])])

    assert result[0]["yKeys"] == []


@pytest.mark.parametrize("aggregation", ["sum", "avg", "min", "max"])
def test_sanitize_requires_a_numeric_y_key_for_numeric_aggregations(aggregation):
    """Summing a string column is not something the client can evaluate"""
    assert _sanitize([_chart(aggregation=aggregation, yKeys=["aceito"])]) == []


@pytest.mark.parametrize("aggregation", ["sum", "avg", "min", "max"])
def test_sanitize_keeps_numeric_y_keys_for_numeric_aggregations(aggregation):
    """A numeric column is the one thing those aggregations accept"""
    result = _sanitize([_chart(aggregation=aggregation, yKeys=["valor"])])

    assert result[0]["yKeys"] == ["valor"]


def test_sanitize_drops_a_numeric_aggregation_with_no_y_keys():
    """There is nothing to sum without a measure column"""
    assert _sanitize([_chart(aggregation="sum", yKeys=[])]) == []


def test_sanitize_allows_aggregation_none_without_y_keys():
    """ "none" plots raw values and does not require a measure"""
    assert _sanitize([_chart(aggregation="none", yKeys=[])])[0]["yKeys"] == []


def test_sanitize_limits_a_pie_chart_to_one_y_key():
    """A pie has a single ring: only the first measure is kept"""
    columns = COLUMNS + [{"key": "outro", "label": "Outro", "type": "number"}]
    result = _sanitize(
        [_chart(type="pie", aggregation="sum", yKeys=["valor", "outro"])],
        _request(columns=columns),
    )

    assert result[0]["yKeys"] == ["valor"]


def test_sanitize_keeps_several_y_keys_on_a_bar_chart():
    """Bars can be stacked, so more than one measure is legitimate"""
    columns = COLUMNS + [{"key": "outro", "label": "Outro", "type": "number"}]
    result = _sanitize(
        [_chart(aggregation="sum", yKeys=["valor", "outro"])],
        _request(columns=columns),
    )

    assert result[0]["yKeys"] == ["valor", "outro"]


# ---------------------------------------------------------------------------
# _sanitize_suggestions: series take precedence over aggregation
# ---------------------------------------------------------------------------


def test_sanitize_lets_a_series_replace_the_aggregation():
    """A computed metric forces aggregation "none" and empty yKeys"""
    result = _sanitize(
        [
            _chart(
                aggregation="sum",
                yKeys=["valor"],
                series=[{"expr": "soma(valor) / contagem() * 100", "label": "Taxa"}],
            )
        ]
    )

    assert result[0]["aggregation"] == "none"
    assert result[0]["yKeys"] == []
    assert result[0]["series"] == [
        {"expr": "soma(valor) / contagem() * 100", "label": "Taxa"}
    ]


def test_sanitize_falls_back_to_the_aggregation_when_the_series_is_unusable():
    """An empty series is no series: the plain aggregation is validated instead"""
    result = _sanitize([_chart(series=[{"label": "sem expr"}])])

    assert "series" not in result[0]
    assert result[0]["aggregation"] == "count"


def test_sanitize_still_validates_the_x_key_of_a_series_chart():
    """Series bypass the aggregation rules, not the column schema"""
    assert (
        _sanitize([_chart(xKeys=["nao_existe"], series=[{"expr": "contagem()"}])]) == []
    )


def test_sanitize_accepts_a_series_with_an_invalid_aggregation():
    """With a valid series the aggregation field is overwritten, not checked"""
    result = _sanitize([_chart(aggregation="median", series=[{"expr": "contagem()"}])])

    assert result[0]["aggregation"] == "none"


# ---------------------------------------------------------------------------
# _sanitize_suggestions: optional display fields
# ---------------------------------------------------------------------------


def test_sanitize_keeps_date_grouping_on_a_date_column():
    """dateGrouping is meaningful only over a date axis, and here it is one"""
    result = _sanitize([_chart(xKeys=["data"], dateGrouping="month")])

    assert result[0]["dateGrouping"] == "month"


def test_sanitize_drops_date_grouping_on_a_non_date_column():
    """Grouping a string dimension by month is nonsense, so the field goes"""
    result = _sanitize([_chart(xKeys=["setor"], dateGrouping="month")])

    assert "dateGrouping" not in result[0]


def test_sanitize_drops_an_unknown_date_grouping():
    """Only the documented granularities survive"""
    result = _sanitize([_chart(xKeys=["data"], dateGrouping="fortnight")])

    assert "dateGrouping" not in result[0]


@pytest.mark.parametrize("sort_order", ["none", "asc", "desc"])
def test_sanitize_keeps_a_valid_sort_order(sort_order):
    """The three documented sort orders pass through"""
    assert _sanitize([_chart(sortOrder=sort_order)])[0]["sortOrder"] == sort_order


def test_sanitize_drops_an_unknown_sort_order():
    """An unrecognised sort order is removed rather than guessed at"""
    assert "sortOrder" not in _sanitize([_chart(sortOrder="random")])[0]


@pytest.mark.parametrize("width", ["full", "half"])
def test_sanitize_keeps_a_valid_width(width):
    """Both layout widths are honoured"""
    assert _sanitize([_chart(width=width)])[0]["width"] == width


@pytest.mark.parametrize("width", ["wide", "", None, 100])
def test_sanitize_defaults_an_invalid_width_to_half(width):
    """Width always has a value, because the grid needs one"""
    assert _sanitize([_chart(width=width)])[0]["width"] == "half"


def test_sanitize_keeps_a_non_negative_integer_top_n():
    """topN caps the categories drawn and must be a count"""
    assert _sanitize([_chart(topN=10)])[0]["topN"] == 10
    assert _sanitize([_chart(topN=0)])[0]["topN"] == 0


@pytest.mark.parametrize("top_n", [-1, "10", 10.5, None])
def test_sanitize_drops_an_invalid_top_n(top_n):
    """A negative, fractional or textual topN is discarded"""
    assert "topN" not in _sanitize([_chart(topN=top_n)])[0]


def test_sanitize_keeps_a_boolean_stacked_flag():
    """stacked is a boolean the renderer reads directly"""
    assert _sanitize([_chart(stacked=True)])[0]["stacked"] is True
    assert _sanitize([_chart(stacked=False)])[0]["stacked"] is False


@pytest.mark.parametrize("stacked", ["true", 1, None])
def test_sanitize_drops_a_non_boolean_stacked_flag(stacked):
    """A truthy string is not a boolean and is dropped instead of coerced"""
    assert "stacked" not in _sanitize([_chart(stacked=stacked)])[0]


# ---------------------------------------------------------------------------
# _prompt_sonnet: the Bedrock call
# ---------------------------------------------------------------------------


def test_prompt_sonnet_returns_the_parsed_model_answer(monkeypatch):
    """The model's text payload is unwrapped and parsed as JSON"""
    client = _bedrock_client('[{"type": "bar"}]')
    monkeypatch.setattr(
        reports_custom_service.aws, "get_client", lambda *a, **k: client
    )

    result = reports_custom_service._prompt_sonnet(messages=[], system="s")

    assert result == [{"type": "bar"}]


def test_prompt_sonnet_sends_the_configured_model_and_token_budget(monkeypatch):
    """The request carries the pinned model id and the Bedrock envelope"""
    client = _bedrock_client("[]")
    monkeypatch.setattr(
        reports_custom_service.aws, "get_client", lambda *a, **k: client
    )

    reports_custom_service._prompt_sonnet(
        messages=[{"role": "user", "content": "oi"}], system="sistema"
    )

    kwargs = client.invoke_model.call_args.kwargs
    body = json.loads(kwargs["body"])

    assert kwargs["modelId"] == reports_custom_service.CHART_SUGGESTION_MODEL_ID
    assert body["max_tokens"] == reports_custom_service.CHART_SUGGESTION_MAX_TOKENS
    assert body["anthropic_version"] == "bedrock-2023-05-31"
    assert body["system"] == "sistema"
    assert body["messages"] == [{"role": "user", "content": "oi"}]


def test_prompt_sonnet_turns_a_bedrock_failure_into_service_unavailable(monkeypatch):
    """An unreachable model is a 503, not a leaked boto exception"""
    client = MagicMock()
    client.invoke_model.side_effect = Exception("throttled")
    monkeypatch.setattr(
        reports_custom_service.aws, "get_client", lambda *a, **k: client
    )

    with pytest.raises(ValidationError) as exc:
        reports_custom_service._prompt_sonnet(messages=[], system="s")

    assert exc.value.code == "errors.serviceUnavailable"
    assert exc.value.httpStatus == status.HTTP_503_SERVICE_UNAVAILABLE


# ---------------------------------------------------------------------------
# suggest_graphs: prompt assembly and the sanitized result
# ---------------------------------------------------------------------------


def test_suggest_graphs_returns_the_sanitized_chart(monkeypatch):
    """End to end: the model answers, the sanitizer cleans, the client gets one chart"""
    client = _bedrock_client(
        json.dumps([_chart(sql="select 1", topN="10", width="wide")])
    )
    monkeypatch.setattr(
        reports_custom_service.aws, "get_client", lambda *a, **k: client
    )

    result = _suggest_graphs(request_data=_request())

    assert result == [_chart(width="half")]


def test_suggest_graphs_describes_the_report_in_the_prompt(monkeypatch):
    """The model is told the schema, the sample rows, the hint and what exists already"""
    client = _bedrock_client("[]")
    monkeypatch.setattr(
        reports_custom_service.aws, "get_client", lambda *a, **k: client
    )

    _suggest_graphs(
        request_data=_request(
            hint="quero ver aceitação por setor",
            existing_titles=["Incidência por Germe"],
        )
    )

    body = json.loads(client.invoke_model.call_args.kwargs["body"])
    user_message = body["messages"][0]["content"]

    assert '"key": "setor"' in user_message
    assert "UTI" in user_message
    assert "quero ver aceitação por setor" in user_message
    assert "Incidência por Germe" in user_message


def test_suggest_graphs_marks_an_absent_hint_explicitly(monkeypatch):
    """With no hint the prompt says so rather than trailing off empty"""
    client = _bedrock_client("[]")
    monkeypatch.setattr(
        reports_custom_service.aws, "get_client", lambda *a, **k: client
    )

    _suggest_graphs(request_data=_request())

    body = json.loads(client.invoke_model.call_args.kwargs["body"])

    assert "User hint: (none)" in body["messages"][0]["content"]


def test_suggest_graphs_truncates_sample_values_in_the_prompt(monkeypatch):
    """Long cell values are trimmed on the way in, not sent whole"""
    client = _bedrock_client("[]")
    monkeypatch.setattr(
        reports_custom_service.aws, "get_client", lambda *a, **k: client
    )

    _suggest_graphs(request_data=_request(rows=[{"setor": "U" * 500}]))

    body = json.loads(client.invoke_model.call_args.kwargs["body"])

    assert "U" * 120 in body["messages"][0]["content"]
    assert "U" * 121 not in body["messages"][0]["content"]


def test_suggest_graphs_caps_the_column_options_sent_to_the_model(monkeypatch):
    """Only the first 20 distinct options of a column are worth the tokens"""
    client = _bedrock_client("[]")
    monkeypatch.setattr(
        reports_custom_service.aws, "get_client", lambda *a, **k: client
    )

    columns = [
        {
            "key": "setor",
            "label": "Setor",
            "type": "string",
            "options": [f"OPT{i}" for i in range(50)],
        }
    ]
    _suggest_graphs(request_data=_request(columns=columns))

    body = json.loads(client.invoke_model.call_args.kwargs["body"])
    user_message = body["messages"][0]["content"]

    assert '"OPT19"' in user_message
    assert '"OPT20"' not in user_message


def test_suggest_graphs_drops_a_chart_built_on_an_invented_column(monkeypatch):
    """A hallucinated column key must never reach the client as a chart"""
    client = _bedrock_client(json.dumps([_chart(xKeys=["coluna_inventada"])]))
    monkeypatch.setattr(
        reports_custom_service.aws, "get_client", lambda *a, **k: client
    )

    assert _suggest_graphs(request_data=_request()) == []


def test_suggest_graphs_rejects_a_non_json_answer(monkeypatch):
    """Prose from the model surfaces as a validation error"""
    client = _bedrock_client("Não consigo sugerir um gráfico.")
    monkeypatch.setattr(
        reports_custom_service.aws, "get_client", lambda *a, **k: client
    )

    with pytest.raises(ValidationError) as exc:
        _suggest_graphs(request_data=_request())

    assert exc.value.code == "errors.invalidParams"


# ---------------------------------------------------------------------------
# _get_resource_path: the download path guard
# ---------------------------------------------------------------------------


def test_resource_path_is_built_per_schema_and_report():
    """Custom report files are namespaced by schema and report id"""
    path = reports_custom_service._get_resource_path(
        id_report=7, schema="demo", filename="20260101.csv"
    )

    assert path == "reports/demo/CUSTOM/7/20260101.csv"


@pytest.mark.parametrize(
    "filename",
    [
        "../../../etc/passwd",  # traversal
        "x.exe",  # extension outside the allowed set
        "arquivo com espaco.csv",  # space
        "x.csv\x00",  # null byte
        "",  # empty
    ],
)
def test_resource_path_refuses_a_filename_outside_the_report_folder(filename):
    """The guard runs before S3 is touched, so a crafted name never resolves"""
    with pytest.raises(ValidationError) as exc:
        reports_custom_service._get_resource_path(
            id_report=7, schema="demo", filename=filename
        )

    assert exc.value.code == "errors.invalidFilename"
