"""Test: CONTAINS expressions in protocol variables

A CONTAINS value stays a plain string, but it may join several texts: ``&``
requires all of them and ``|`` accepts any of them (``&`` binds tighter). A value
without separators keeps matching as a plain substring. Matching ignores case
and accents. The same rule backs ``insurance``, ``dischargeReason`` and the
``observation`` criterion of a combination.
"""

import pytest

from models.prescription import Patient, Prescription
from tests.utils import utils_test_prescription
from utils import contains_expression
from utils.alert_protocol import AlertProtocol
from utils.alert_protocol_trace import build_variable_message

RESULT = {"type": "SHOW_MESSAGE", "level": "high", "message": "test"}

NOTES = "Infundir em BIC a 20 ml/min; ajustar gotejo conforme sedação"


# ---------------------------------------------------------------------------
# helper module
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("ml/min", True),
        ("ML/MIN", True),
        ("ml/min & gotejo", True),
        ("ml/min&gotejo", True),
        ("  ml/min   &   gotejo  ", True),
        ("ml/min & bolus", False),
        ("bolus & gotejo", False),
        ("bolus | gotejo", True),
        ("bolus | ataque", False),
        ("bolus & ataque | ml/min & gotejo", True),
        ("bolus & gotejo | ataque", False),
        ("sedacao", True),  # accents are ignored on the text side
        ("sedação & gotejo", True),
        ("gotéjo", True),  # and on the value side
        ("20 ml", True),  # a plain value is matched untrimmed, as before
        ("mg/kg", False),
    ],
)
def test_matches(value, expected):
    """contains_expression.matches: AND/OR groups, case and accent insensitive"""

    assert contains_expression.matches(text=NOTES, value=value) is expected


@pytest.mark.parametrize("text,value", [(None, "a"), ("a", None), (None, None)])
def test_matches_without_data(text, value):
    """contains_expression.matches: a missing text or value never matches"""

    assert contains_expression.matches(text=text, value=value) is False


@pytest.mark.parametrize(
    "value,groups",
    [
        ("ml/min", [["ml/min"]]),
        (" ml/min ", [[" ml/min "]]),
        ("ml/min & gotejo", [["ml/min", "gotejo"]]),
        ("a & b | c", [["a", "b"], ["c"]]),
        ("a & & b", [["a", "b"]]),  # blank terms are dropped at runtime
        ("&", [["&"]]),  # nothing but separators: literal fallback
    ],
)
def test_parse_expression(value, groups):
    """contains_expression.parse_expression: OR groups of AND terms"""

    assert contains_expression.parse_expression(value) == groups


@pytest.mark.parametrize(
    "value,expected",
    [
        ("ml/min", False),
        ("ml/min & gotejo", False),
        ("a & b | c", False),
        ("ml/min & ", True),
        ("& gotejo", True),
        ("a || b", True),
        ("a | & b", True),
        ("|", True),
        (None, False),
    ],
)
def test_has_empty_term(value, expected):
    """contains_expression.has_empty_term: flags blank terms around separators"""

    assert contains_expression.has_empty_term(value) is expected


def test_missing_terms():
    """contains_expression.missing_terms: lists the texts not found"""

    assert contains_expression.missing_terms(
        text=NOTES, value="ml/min & bolus | ataque"
    ) == ["bolus", "ataque"]
    assert contains_expression.missing_terms(text=None, value="a & b") == ["a", "b"]


def test_describe():
    """contains_expression.describe: readable Portuguese form"""

    assert (
        contains_expression.describe("ml/min & gotejo | bic")
        == "'ml/min' e 'gotejo' ou 'bic'"
    )


# ---------------------------------------------------------------------------
# protocol evaluation
# ---------------------------------------------------------------------------


def _get_alert_protocol(drug_list=None, prescription=None, patient=None):
    """Builds an AlertProtocol instance with minimal mock data"""

    if prescription is None:
        prescription = Prescription()
        prescription.idDepartment = 100

    return AlertProtocol(
        drugs=drug_list if drug_list is not None else [],
        exams={},
        prescription=prescription,
        patient=patient if patient is not None else Patient(),
        cn_stats={},
    )


def _drug_list():
    return [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=1,
            dose=10,
            drug_name="Drug A",
            route="IV",
            notes=NOTES,
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=2,
            dose=20,
            drug_name="Drug B",
            route="IV",
            notes="Correr em 30 min",
        ),
    ]


def _protocol(variable: dict):
    return {
        "variables": [{"name": "v1", **variable}],
        "trigger": "{{v1}}",
        "result": RESULT.copy(),
    }


@pytest.mark.parametrize(
    "observation,related_items",
    [
        ("ml/min & gotejo", [1]),
        ("ml/min & bolus", []),
        ("gotejo | 30 min", [1, 2]),
        ("bolus | 30 MIN", [2]),
        ("Take with food", []),
    ],
)
def test_combination_observation(observation, related_items):
    """combination.observation: matches the item notes with the expression"""

    alert_protocol = _get_alert_protocol(drug_list=_drug_list())
    result = alert_protocol.get_protocol_alerts(
        protocol=_protocol(
            {"field": "combination", "route": ["IV"], "observation": observation}
        )
    )

    assert (result is not None) is (len(related_items) > 0)
    assert sorted(alert_protocol.related_items) == related_items


@pytest.mark.parametrize(
    "value,has_result",
    [
        ("ficticio & especial", True),
        ("ficticio & basico", False),
        ("sus | ficticio", True),
    ],
)
def test_insurance(value, has_result):
    """insurance: CONTAINS accepts the expression syntax"""

    prescription = Prescription()
    prescription.idDepartment = 100
    prescription.insurance = "PLANO FICTICIO Especial"

    result = _get_alert_protocol(prescription=prescription).get_protocol_alerts(
        protocol=_protocol(
            {"field": "insurance", "operator": "CONTAINS", "value": value}
        )
    )

    assert (result is not None) is has_result


@pytest.mark.parametrize(
    "value,has_result",
    [("obito | óbito", True), ("alta & melhorada", False)],
)
def test_discharge_reason(value, has_result):
    """dischargeReason: CONTAINS accepts the expression syntax"""

    patient = Patient()
    patient.dischargeReason = "Óbito"

    result = _get_alert_protocol(patient=patient).get_protocol_alerts(
        protocol=_protocol(
            {"field": "dischargeReason", "operator": "CONTAINS", "value": value}
        )
    )

    assert (result is not None) is has_result


# ---------------------------------------------------------------------------
# trace messages
# ---------------------------------------------------------------------------


def test_trace_lists_missing_terms():
    """trace: a failed expression names the texts that were not found"""

    prescription = Prescription()
    prescription.idDepartment = 100
    prescription.insurance = "PLANO FICTICIO Especial"

    trace = _get_alert_protocol(prescription=prescription).evaluate_with_trace(
        protocol=_protocol(
            {"field": "insurance", "operator": "CONTAINS", "value": "ficticio & basico"}
        )
    )
    variable = trace["variables"][0]

    assert variable.result is False
    assert variable.details["missing"] == ["basico"]

    message = build_variable_message(variable)
    assert "esperado conter 'ficticio' e 'basico'" in message
    assert "não encontrado: 'basico'" in message


def test_trace_plain_value_message_is_unchanged():
    """trace: a plain value keeps the original message"""

    prescription = Prescription()
    prescription.idDepartment = 100
    prescription.insurance = "SUS"

    trace = _get_alert_protocol(prescription=prescription).evaluate_with_trace(
        protocol=_protocol(
            {"field": "insurance", "operator": "CONTAINS", "value": "ficticio"}
        )
    )

    assert build_variable_message(trace["variables"][0]) == (
        "Variável 'v1' (convênio): o valor encontrado foi 'SUS'; "
        "esperado conter o texto 'ficticio' → falso"
    )


def test_trace_combination_describes_the_expression():
    """trace: a combination that failed on observation describes the expression"""

    trace = _get_alert_protocol(drug_list=_drug_list()).evaluate_with_trace(
        protocol=_protocol(
            {"field": "combination", "route": ["IV"], "observation": "bolus & ataque"}
        )
    )

    message = build_variable_message(trace["variables"][0])
    assert "esperado: contém o texto 'bolus' e 'ataque'" in message
