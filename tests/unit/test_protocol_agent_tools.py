"""Unit tests for the protocol co-pilot tool set.

``protocol_agent_tools.build_tools`` exposes the catalogs of the tenant to the
protocol-creation agent: substances, classes, hospital drugs, ICDs, exam types,
global reference exams, departments, segments, routes, patient tags and the
NoHarm Care indicators, plus the two tools that close the self-correction loop
(``validate_protocol`` and ``test_protocol``).

The tools are what the model reads before it writes a protocol config, so their
shape is a correctness concern and not a presentation detail:

* the ids the agent must copy have to come back under the documented key
  (``examType`` lowercased, ``tpexam`` verbatim, ``statsType``, ...);
* a truncated listing has to say so — an unreported cap is what pushes the
  model to invent ids it "could not find";
* every call re-applies the tenant schema, because the tools run inside the
  Strands worker thread;
* a broken lookup becomes an error tool result instead of aborting the turn.

The underlying services are patched: this file tests the tool wrappers, not the
catalogs themselves.
"""

from types import SimpleNamespace
from unittest import mock

import pytest

from models.enums import TagTypeEnum
from repository import exams_repository, tag_repository
from services import (
    clinical_notes_service,
    drug_service,
    lists_service,
    protocol_trace_service,
    segment_service,
    substance_service,
)
from services.admin import admin_protocol_service
from services.protocol_agent_tools import (
    MAX_EXAM_TYPE_RESULTS,
    MAX_REFERENCE_EXAM_RESULTS,
    MAX_RESULTS,
    MAX_TEST_PRESCRIPTIONS,
    _filter_items,
    build_tools,
)


def _tools(validate_config=None, normalize_config=None):
    """Build the tool set keyed by tool name, with the injected callables stubbed."""
    tools = build_tools(
        schema="demo",
        validate_config=validate_config or (lambda config, protocol_type: []),
        normalize_config=normalize_config or (lambda config: config),
    )

    return {tool.tool_spec["name"]: tool for tool in tools}


def _call(name, **kwargs):
    """Invoke a tool by name with the tenant schema switch stubbed out."""
    with mock.patch("services.protocol_agent_tools.dbSession.setSchema") as set_schema:
        output = _tools()[name]._tool_func(**kwargs)

    return output, set_schema


def _result(output):
    """Unwrap the payload of a successful tool result."""
    assert output["status"] == "success", output
    return output["content"][0]["json"]["result"]


def _items(output):
    """Unwrap the items of a successful list tool result."""
    return _result(output)["items"]


def _exam_type(type_exam, name):
    """Build a get_exam_types() row (typeExam, name)."""
    return SimpleNamespace(typeExam=type_exam, name=name)


def _global_exam(tp_exam, name, initials="", measureunit=""):
    """Build a get_global_exams() row."""
    return SimpleNamespace(
        tp_exam=tp_exam, name=name, initials=initials, measureunit=measureunit
    )


# --------------------------------------------------------------------------
# the tool set itself
# --------------------------------------------------------------------------


def test_the_documented_tool_set_is_exposed():
    """The agent prompt names these tools: a rename here breaks the turn"""
    assert set(_tools()) == {
        "search_substances",
        "search_substance_classes",
        "search_drugs",
        "search_icds",
        "search_exam_types",
        "search_reference_exams",
        "list_departments",
        "list_segments",
        "list_routes",
        "list_tags",
        "list_stats_types",
        "validate_protocol",
        "test_protocol",
    }


def test_every_tool_is_described_for_the_model():
    """A tool without a description is invisible to the agent"""
    for name, tool in _tools().items():
        assert tool.tool_spec["description"].strip(), name


# --------------------------------------------------------------------------
# _filter_items
# --------------------------------------------------------------------------


def test_filter_without_a_term_keeps_everything():
    """Omitting the term is how the agent lists a whole catalog"""
    items = [{"name": "a"}, {"name": "b"}]

    assert _filter_items(items, None, ("name",)) == items
    assert _filter_items(items, "", ("name",)) == items


def test_filter_with_a_blank_term_keeps_everything():
    """A term the model padded with spaces is not a filter"""
    items = [{"name": "a"}]

    assert _filter_items(items, "   ", ("name",)) == items


def test_filter_matches_a_case_insensitive_substring():
    """The model rarely reproduces the exact casing of a catalog entry"""
    items = [{"name": "Potássio"}, {"name": "Sódio"}]

    assert _filter_items(items, "POTÁS", ("name",)) == [{"name": "Potássio"}]


def test_filter_searches_every_given_key():
    """A hit on any of the keys keeps the item"""
    items = [{"examType": "k", "name": "Potássio"}]

    assert _filter_items(items, "potássio", ("examType", "name")) == items
    assert _filter_items(items, "k", ("examType", "name")) == items


def test_filter_ignores_the_keys_it_was_not_given():
    """A term matching only an unsearched key is not a hit"""
    items = [{"examType": "k", "name": "Potássio"}]

    assert _filter_items(items, "potássio", ("examType",)) == []


def test_filter_tolerates_missing_and_null_values():
    """A catalog row with a null column must not break the search"""
    items = [{"name": None}, {}, {"name": "Sódio"}]

    assert _filter_items(items, "sód", ("name",)) == [{"name": "Sódio"}]


def test_filter_trims_the_term_before_matching():
    """A padded term still matches"""
    items = [{"name": "Sódio"}]

    assert _filter_items(items, "  sódio  ", ("name",)) == items


# --------------------------------------------------------------------------
# schema handling and error handling (_run)
# --------------------------------------------------------------------------


def test_the_tenant_schema_is_applied_on_every_call():
    """Tools run in the Strands worker thread, which has no request schema"""
    with mock.patch.object(substance_service, "find_substance", return_value=[]):
        _, set_schema = _call("search_substances", term="x")

    set_schema.assert_called_once_with("demo")


def test_a_failing_lookup_becomes_an_error_tool_result():
    """A broken catalog must not abort the chat turn"""
    with mock.patch.object(
        substance_service, "find_substance", side_effect=Exception("boom")
    ):
        output, _ = _call("search_substances", term="x")

    assert output["status"] == "error"
    assert "boom" in output["content"][0]["text"]


def test_an_error_message_is_truncated():
    """A stack-trace-sized error would eat the agent context window"""
    with mock.patch.object(
        substance_service, "find_substance", side_effect=Exception("x" * 5000)
    ):
        output, _ = _call("search_substances", term="x")

    assert len(output["content"][0]["text"]) < 400


def test_a_failing_lookup_is_logged():
    """The failure is invisible in the transcript, so it has to be logged"""
    with (
        mock.patch.object(
            substance_service, "find_substance", side_effect=Exception("boom")
        ),
        mock.patch("services.protocol_agent_tools.logger.backend_logger") as log,
    ):
        _call("search_substances", term="x")

    log.warning.assert_called_once()


def test_a_schema_failure_becomes_an_error_tool_result():
    """The schema switch itself is inside the guarded block"""
    with (
        mock.patch(
            "services.protocol_agent_tools.dbSession.setSchema",
            side_effect=Exception("no connection"),
        ),
        mock.patch.object(substance_service, "find_substance", return_value=[]),
    ):
        output = _tools()["search_substances"]._tool_func(term="x")

    assert output["status"] == "error"


# --------------------------------------------------------------------------
# catalog searches delegated as-is
# --------------------------------------------------------------------------


def test_search_substances_delegates_the_term():
    """The tool is a thin wrapper over the substance search"""
    rows = [{"sctid": "111", "name": "Potássio"}]

    with mock.patch.object(
        substance_service, "find_substance", return_value=rows
    ) as find:
        output, _ = _call("search_substances", term="pot")

    find.assert_called_once_with("pot")
    assert _items(output) == rows


def test_search_substance_classes_delegates_the_term():
    """Class ids feed the `class` variable type"""
    rows = [{"id": "A10", "name": "Antidiabéticos"}]

    with mock.patch.object(
        substance_service, "find_substance_class", return_value=rows
    ) as find:
        output, _ = _call("search_substance_classes", term="anti")

    find.assert_called_once_with("anti")
    assert _items(output) == rows


def test_search_drugs_delegates_the_term():
    """Hospital drugs come from the protocol-specific drug search"""
    rows = [{"idDrug": 1, "name": "Dipirona"}]

    with mock.patch.object(
        drug_service, "find_protocol_drugs", return_value=rows
    ) as find:
        output, _ = _call("search_drugs", term="dipi")

    find.assert_called_once_with("dipi")
    assert _items(output) == rows


def test_search_icds_delegates_the_term():
    """ICDs are searched by code or description"""
    rows = [{"id": "C50", "name": "Neoplasia"}]

    with mock.patch.object(lists_service, "find_icds", return_value=rows) as find:
        output, _ = _call("search_icds", term="c50")

    find.assert_called_once_with("c50")
    assert _items(output) == rows


def test_list_routes_delegates():
    """Routes take no search term"""
    rows = [{"id": "IV", "name": "Intravenosa"}]

    with mock.patch.object(lists_service, "list_routes", return_value=rows) as list_fn:
        output, _ = _call("list_routes")

    list_fn.assert_called_once_with()
    assert _items(output) == rows


def test_list_departments_delegates():
    """Departments carry the segments they belong to"""
    rows = [{"idDepartment": 1, "name": "UTI", "segments": [1]}]

    with mock.patch.object(
        admin_protocol_service, "list_departments", return_value=rows
    ) as list_fn:
        output, _ = _call("list_departments")

    list_fn.assert_called_once_with()
    assert _items(output) == rows


# --------------------------------------------------------------------------
# search_exam_types
# --------------------------------------------------------------------------


def test_exam_types_are_lowercased():
    """`exam` variables are matched in lowercase at runtime"""
    with mock.patch.object(
        exams_repository, "get_exam_types", return_value=[_exam_type("K", "Potássio")]
    ):
        output, _ = _call("search_exam_types")

    assert _items(output) == [{"examType": "k", "name": "Potássio"}]


def test_exam_types_are_read_from_the_repository_not_the_service():
    """The service hides the calculated exams, which are valid at runtime"""
    rows = [_exam_type("ckd21", "CKD-EPI"), _exam_type("mdrd", "MDRD")]

    with mock.patch.object(exams_repository, "get_exam_types", return_value=rows):
        output, _ = _call("search_exam_types")

    assert [item["examType"] for item in _items(output)] == ["ckd21", "mdrd"]


def test_exam_types_can_be_filtered_by_name():
    """The agent narrows a large catalog with a partial name"""
    rows = [_exam_type("k", "Potássio"), _exam_type("na", "Sódio")]

    with mock.patch.object(exams_repository, "get_exam_types", return_value=rows):
        output, _ = _call("search_exam_types", term="sód")

    assert _items(output) == [{"examType": "na", "name": "Sódio"}]


def test_exam_types_can_be_filtered_by_the_exam_type_itself():
    """The model often knows the examType and only wants to confirm it exists"""
    rows = [_exam_type("K", "Potássio"), _exam_type("NA", "Sódio")]

    with mock.patch.object(exams_repository, "get_exam_types", return_value=rows):
        output, _ = _call("search_exam_types", term="na")

    assert _items(output) == [{"examType": "na", "name": "Sódio"}]


def test_exam_types_report_their_own_cap():
    """A silently truncated catalog is what makes the agent invent ids"""
    rows = [_exam_type(f"e{i}", f"Exame {i}") for i in range(MAX_EXAM_TYPE_RESULTS + 5)]

    with mock.patch.object(exams_repository, "get_exam_types", return_value=rows):
        output, _ = _call("search_exam_types")

    payload = _result(output)
    assert payload["returned"] == MAX_EXAM_TYPE_RESULTS
    assert payload["total"] == MAX_EXAM_TYPE_RESULTS + 5
    assert payload["truncated"] is True


def test_exam_types_are_not_capped_at_the_default_list_size():
    """The exam catalog gets a larger cap than the other listings"""
    rows = [_exam_type(f"e{i}", f"Exame {i}") for i in range(MAX_RESULTS + 10)]

    with mock.patch.object(exams_repository, "get_exam_types", return_value=rows):
        output, _ = _call("search_exam_types")

    assert _result(output)["truncated"] is False


# --------------------------------------------------------------------------
# search_reference_exams
# --------------------------------------------------------------------------


def test_reference_exams_keep_the_tpexam_casing():
    """examRefType is matched verbatim, so the case must survive the tool"""
    with (
        mock.patch.object(
            exams_repository,
            "get_global_exams",
            return_value=[_global_exam("creatinina_NH", "Creatinina", "CR", "mg/dL")],
        ),
        mock.patch.object(
            exams_repository, "get_configured_exam_ref_types", return_value=[]
        ),
    ):
        output, _ = _call("search_reference_exams")

    assert _items(output)[0]["tpexam"] == "creatinina_NH"


def test_reference_exams_flag_the_ones_configured_in_this_hospital():
    """A globally valid tpexam no active exam maps to never fires here"""
    rows = [
        _global_exam("creatinina_NH", "Creatinina"),
        _global_exam("ckd21_NH", "CKD"),
    ]

    with (
        mock.patch.object(exams_repository, "get_global_exams", return_value=rows),
        mock.patch.object(
            exams_repository,
            "get_configured_exam_ref_types",
            return_value=["creatinina_NH"],
        ),
    ):
        output, _ = _call("search_reference_exams")

    flags = {
        item["tpexam"]: item["configuredInThisHospital"] for item in _items(output)
    }
    assert flags == {"creatinina_NH": True, "ckd21_NH": False}


def test_reference_exams_expose_the_measure_unit_and_initials():
    """The agent needs the unit to write a plausible threshold"""
    with (
        mock.patch.object(
            exams_repository,
            "get_global_exams",
            return_value=[_global_exam("creatinina_NH", "Creatinina", "CR", "mg/dL")],
        ),
        mock.patch.object(
            exams_repository, "get_configured_exam_ref_types", return_value=[]
        ),
    ):
        output, _ = _call("search_reference_exams")

    item = _items(output)[0]
    assert item["initials"] == "CR"
    assert item["measureUnit"] == "mg/dL"


def test_reference_exams_can_be_filtered_by_the_initials():
    """Clinicians and the model alike search by abbreviation"""
    rows = [
        _global_exam("creatinina_NH", "Creatinina", "CR"),
        _global_exam("potassio_NH", "Potássio", "K"),
    ]

    with (
        mock.patch.object(exams_repository, "get_global_exams", return_value=rows),
        mock.patch.object(
            exams_repository, "get_configured_exam_ref_types", return_value=[]
        ),
    ):
        output, _ = _call("search_reference_exams", term="cr")

    assert [item["tpexam"] for item in _items(output)] == ["creatinina_NH"]


def test_reference_exams_report_their_own_cap():
    """The reference catalog is capped tighter than the schema exam types"""
    rows = [
        _global_exam(f"e{i}_NH", f"Exame {i}")
        for i in range(MAX_REFERENCE_EXAM_RESULTS + 3)
    ]

    with (
        mock.patch.object(exams_repository, "get_global_exams", return_value=rows),
        mock.patch.object(
            exams_repository, "get_configured_exam_ref_types", return_value=[]
        ),
    ):
        output, _ = _call("search_reference_exams")

    payload = _result(output)
    assert payload["returned"] == MAX_REFERENCE_EXAM_RESULTS
    assert payload["truncated"] is True


# --------------------------------------------------------------------------
# list_segments / list_tags / list_stats_types
# --------------------------------------------------------------------------


def test_segments_are_mapped_to_id_and_description():
    """The whole Segment row would be noise in the agent context"""
    rows = [SimpleNamespace(id=1, description="Adulto", extra="ignored")]

    with mock.patch.object(segment_service, "get_segments", return_value=rows):
        output, _ = _call("list_segments")

    assert _items(output) == [{"id": 1, "description": "Adulto"}]


def test_tags_are_mapped_to_name_and_type():
    """`tags` variables are written with the tag name"""
    rows = [SimpleNamespace(name="Sepse", tag_type=TagTypeEnum.PATIENT.value)]

    with mock.patch.object(tag_repository, "list_tags", return_value=rows):
        output, _ = _call("list_tags")

    assert _items(output) == [{"name": "Sepse", "tagType": TagTypeEnum.PATIENT.value}]


def test_tags_are_requested_active_and_for_both_patient_types():
    """A protocol can key off a navigation tag as well as a patient one"""
    with mock.patch.object(tag_repository, "list_tags", return_value=[]) as list_fn:
        _call("list_tags")

    request_data = list_fn.call_args.kwargs["request_data"]
    assert request_data.active is True
    assert set(request_data.tagTypeList) == {
        TagTypeEnum.PATIENT.value,
        TagTypeEnum.PATIENT_NAVIGATION.value,
    }


def test_stats_types_are_mapped_from_the_clinical_notes_tags():
    """`cn_stats` variables are written with the indicator key"""
    rows = [{"name": "sinais", "column": "signs", "key": "signs"}]

    with mock.patch.object(clinical_notes_service, "get_tags", return_value=rows):
        output, _ = _call("list_stats_types")

    assert _items(output) == [{"statsType": "signs", "name": "sinais"}]


# --------------------------------------------------------------------------
# validate_protocol
# --------------------------------------------------------------------------


def test_validate_protocol_reports_a_valid_config():
    """An empty error list is the agent's signal to present the proposal"""
    config = {"variables": [], "trigger": "{{v1}}"}

    with mock.patch("services.protocol_agent_tools.dbSession.setSchema"):
        output = _tools(validate_config=lambda config, protocol_type: [])[
            "validate_protocol"
        ]._tool_func(config=config, protocol_type=2)

    assert _result(output) == {"valid": True, "errors": []}


def test_validate_protocol_reports_the_errors_verbatim():
    """The error text is the only place the agent sees its own mistake"""
    errors = ["variable v1: unknown examRefType CREAT_FAKE"]

    with mock.patch("services.protocol_agent_tools.dbSession.setSchema"):
        output = _tools(validate_config=lambda config, protocol_type: errors)[
            "validate_protocol"
        ]._tool_func(config={}, protocol_type=2)

    payload = _result(output)
    assert payload["valid"] is False
    assert payload["errors"] == errors


def test_validate_protocol_result_is_not_wrapped_as_a_list():
    """A dict result must pass through: `items` would break the loop"""
    with mock.patch("services.protocol_agent_tools.dbSession.setSchema"):
        output = _tools()["validate_protocol"]._tool_func(config={}, protocol_type=2)

    assert "items" not in _result(output)


def test_validate_protocol_receives_the_config_and_the_protocol_type():
    """Validation depends on the protocol type, so it must be forwarded"""
    validate = mock.MagicMock(return_value=[])
    config = {"trigger": "{{v1}}"}

    with mock.patch("services.protocol_agent_tools.dbSession.setSchema"):
        _tools(validate_config=validate)["validate_protocol"]._tool_func(
            config=config, protocol_type=3
        )

    validate.assert_called_once_with(config=config, protocol_type=3)


# --------------------------------------------------------------------------
# test_protocol
# --------------------------------------------------------------------------


def _valid_config(trigger="{{v1}}"):
    """A config accepted by ProtocolTestRequest (the evaluator validates it)."""
    return {
        "variables": [{"name": "v1", "field": "age", "operator": ">", "value": 60}],
        "trigger": trigger,
        "result": {"type": "SHOW_MESSAGE", "level": "high", "message": "Idoso"},
    }


def _test_protocol(config=None, protocol_type=2, ids=None, normalize_config=None):
    """Invoke the test_protocol tool with the schema switch stubbed out."""
    with mock.patch("services.protocol_agent_tools.dbSession.setSchema"):
        return _tools(normalize_config=normalize_config)["test_protocol"]._tool_func(
            config=config if config is not None else _valid_config(),
            protocol_type=protocol_type,
            id_prescription_list=ids,
        )


def test_test_protocol_uses_the_given_prescriptions():
    """Explicit ids skip the sampling entirely"""
    with (
        mock.patch.object(
            protocol_trace_service, "test_protocol", return_value={"results": []}
        ) as run,
        mock.patch.object(protocol_trace_service, "sample_prescriptions") as sample,
    ):
        output = _test_protocol(ids=[10, 11])

    sample.assert_not_called()
    assert run.call_args.kwargs["request_data"].idPrescriptionList == [10, 11]
    assert _result(output) == {"results": []}


def test_test_protocol_caps_the_number_of_prescriptions():
    """Each prescription is a full evaluation: the cap keeps the turn fast"""
    given = list(range(1, MAX_TEST_PRESCRIPTIONS + 3))

    with mock.patch.object(
        protocol_trace_service, "test_protocol", return_value={}
    ) as run:
        _test_protocol(ids=given)

    ids = run.call_args.kwargs["request_data"].idPrescriptionList
    assert ids == given[:MAX_TEST_PRESCRIPTIONS]
    assert len(ids) == MAX_TEST_PRESCRIPTIONS


def test_test_protocol_samples_prescriptions_when_none_are_given():
    """Omitting the ids is how the agent tests against today's prescriptions"""
    with (
        mock.patch.object(
            protocol_trace_service,
            "sample_prescriptions",
            return_value={"idPrescriptionList": ["7", "8"]},
        ) as sample,
        mock.patch.object(
            protocol_trace_service, "test_protocol", return_value={}
        ) as run,
    ):
        _test_protocol(protocol_type=4)

    sample_request = sample.call_args.kwargs["request_data"]
    assert sample_request.protocolType == 4
    assert sample_request.limit == MAX_TEST_PRESCRIPTIONS
    # the sampler returns strings; the evaluator takes ints
    assert run.call_args.kwargs["request_data"].idPrescriptionList == [7, 8]


def test_test_protocol_reports_when_there_is_nothing_to_test():
    """An empty sample is an answer, not an error"""
    with (
        mock.patch.object(
            protocol_trace_service,
            "sample_prescriptions",
            return_value={"idPrescriptionList": []},
        ),
        mock.patch.object(protocol_trace_service, "test_protocol") as run,
    ):
        output = _test_protocol()

    run.assert_not_called()
    assert "Nenhuma prescrição" in _result(output)["message"]


def test_test_protocol_reports_when_the_sampler_returns_nothing():
    """A sampler response without the key is treated as an empty sample"""
    with (
        mock.patch.object(
            protocol_trace_service, "sample_prescriptions", return_value={}
        ),
        mock.patch.object(protocol_trace_service, "test_protocol") as run,
    ):
        output = _test_protocol()

    run.assert_not_called()
    assert "message" in _result(output)


def test_test_protocol_normalizes_the_config_before_evaluating():
    """A nested combination would be tested as an empty one and match everything"""
    normalized = _valid_config(trigger="{{v1}} and {{v2}}")

    with mock.patch.object(
        protocol_trace_service, "test_protocol", return_value={}
    ) as run:
        _test_protocol(
            config=_valid_config(trigger="{{raw}}"),
            ids=[1],
            normalize_config=lambda config: normalized,
        )

    assert run.call_args.kwargs["request_data"].config.trigger == normalized["trigger"]


def test_test_protocol_asks_for_the_undetailed_trace():
    """The detailed trace is far too large for the agent context"""
    with mock.patch.object(
        protocol_trace_service, "test_protocol", return_value={}
    ) as run:
        _test_protocol(ids=[1])

    assert run.call_args.kwargs["request_data"].detailed is False


def test_test_protocol_forwards_the_protocol_type():
    """The evaluator needs the type to resolve the variables"""
    with mock.patch.object(
        protocol_trace_service, "test_protocol", return_value={}
    ) as run:
        _test_protocol(protocol_type=5, ids=[1])

    assert run.call_args.kwargs["request_data"].protocolType == 5


def test_test_protocol_failure_becomes_an_error_tool_result():
    """A protocol the evaluator chokes on must not abort the turn"""
    with mock.patch.object(
        protocol_trace_service, "test_protocol", side_effect=Exception("bad config")
    ):
        output = _test_protocol(ids=[1])

    assert output["status"] == "error"
    assert "bad config" in output["content"][0]["text"]


@pytest.mark.parametrize(
    "name",
    [
        "search_substances",
        "search_substance_classes",
        "search_drugs",
        "search_icds",
    ],
)
def test_delegated_searches_report_the_default_cap(name):
    """Every plain catalog search shares the default list size"""
    rows = [{"id": i} for i in range(MAX_RESULTS + 2)]

    with (
        mock.patch.object(substance_service, "find_substance", return_value=rows),
        mock.patch.object(substance_service, "find_substance_class", return_value=rows),
        mock.patch.object(drug_service, "find_protocol_drugs", return_value=rows),
        mock.patch.object(lists_service, "find_icds", return_value=rows),
    ):
        output, _ = _call(name, term="x")

    payload = _result(output)
    assert payload["returned"] == MAX_RESULTS
    assert payload["truncated"] is True
