"""Tests: POST /admin/protocol/upsert — validation of the trigger variables.

A protocol's ``config.variables`` is the list of named criteria its trigger
expression refers to (``{{v1}} and {{v2}}``). Each entry names a ``field`` —
what to look at: the patient's age, an exam, a NoHarm Care indicator, a
combination of prescribed items — plus, for most fields, the ``operator`` and
``value`` to compare it against. The protocol editor hands this list over
verbatim, so ``admin_protocol_service._validate_variables`` is the only thing
standing between a mistyped criterion and a clinical alert that silently never
fires (or fires on everyone).

Validation runs *before* the config is stored, so a rejected protocol leaves no
trace. It is also not purely a check: it strips the keys the editor leaves
behind empty, and what it strips is what gets persisted.

``test_admin_protocol.py`` covers the schema-ownership rules of the same
endpoint. This module covers the variable rules:

* a protocol must define at least one variable, and an ITEM protocol must
  define a ``combination`` one;
* name, field and a known field type are mandatory;
* ``exam`` needs an exam type and ``cn_stats`` needs an indicator;
* a comparison needs an operator from the allowed set and a value, with ``"0"``
  explicitly a value and ``IN``/``NOTIN`` the only operators taking a list;
* a ``combination`` is validated by its own rules — its empty keys are dropped
  rather than rejected, and only its ``*Operator`` keys are operator-checked;
* an empty ``examPeriod`` is dropped from the stored config.
"""

import json

import pytest
from sqlalchemy import bindparam, text

from models.enums import ProtocolTypeEnum
from tests.conftest import session, session_commit
from utils import status

UPSERT_URL = "/admin/protocol/upsert"

# Rows live in the shared public.protocolo table. The 9902xx range is reserved
# for this module: test_protocol.py owns 9900xx and test_admin_protocol.py 9901xx.
_PROTOCOL_ID = 990201

_STATUS_INACTIVE = 2

_RESULT = {"level": "high", "message": "ZZTest", "description": "ZZTest"}

# the shape every accepted protocol in this module is built from
_AGE_VARIABLE = {"name": "v1", "field": "age", "operator": ">", "value": "60"}

# a field whose values are a set, used for the IN/NOTIN rules: comparing an age
# against a list is well-formed to the validator but meaningless to evaluate
_ROUTE_VARIABLE = {"name": "v1", "field": "route", "operator": "IN", "value": ["IV"]}

# an ITEM protocol must carry one of these; combination keys are not
# operator/value pairs, they are lists of ids plus their own operators
_COMBINATION_VARIABLE = {
    "name": "v1",
    "field": "combination",
    "operator": "IN",
    "route": ["IV"],
}


@pytest.fixture(autouse=True)
def clean_protocol():
    """No protocol of this module survives a test, accepted or rejected."""
    _delete_protocol()
    yield
    _delete_protocol()


def _delete_protocol():
    session.execute(
        text("DELETE FROM public.protocolo WHERE idprotocolo IN :ids").bindparams(
            bindparam("ids", expanding=True)
        ),
        {"ids": [_PROTOCOL_ID]},
    )
    session_commit()


def _seed_protocol(protocol_type=ProtocolTypeEnum.PRESCRIPTION_AGG.value):
    """Insert the protocol this module edits, so upsert takes the update path."""
    session.execute(
        text(
            "INSERT INTO public.protocolo "
            "(idprotocolo, schema_name, nome, tp_protocolo, tp_situacao, "
            "configuracao, created_at, created_by) "
            "VALUES (:id, 'demo', 'ZZTest Protocol Variables', :type, :st, "
            "CAST(:config AS json), now(), 1)"
        ),
        {
            "id": _PROTOCOL_ID,
            "type": protocol_type,
            "st": _STATUS_INACTIVE,
            "config": json.dumps(
                {"variables": [_AGE_VARIABLE], "trigger": "{{v1}}", "result": _RESULT}
            ),
        },
    )
    session_commit()


def _upsert(
    client,
    headers,
    variables,
    protocol_type=ProtocolTypeEnum.PRESCRIPTION_AGG.value,
    trigger="{{v1}}",
):
    """Save the seeded protocol with ``variables`` as its criteria."""
    _seed_protocol(protocol_type=protocol_type)

    return client.post(
        UPSERT_URL,
        headers=headers,
        json={
            "id": _PROTOCOL_ID,
            "name": "ZZTest Protocol Variables",
            "protocolType": protocol_type,
            "statusType": _STATUS_INACTIVE,
            "config": {
                "variables": variables,
                "trigger": trigger,
                "result": _RESULT,
            },
        },
    )


def _stored_variables():
    """The variables as they were persisted — validation rewrites them."""
    session_commit()
    config = session.execute(
        text("SELECT configuracao FROM public.protocolo WHERE idprotocolo = :id"),
        {"id": _PROTOCOL_ID},
    ).scalar()

    return config["variables"]


def _assert_rejected(response):
    """A rejected protocol answers 400 and is not written."""
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    # the stored config must still be the seeded one, untouched by the attempt
    assert _stored_variables() == [_AGE_VARIABLE]


# --- the variable list as a whole ----------------------------------------------


def test_a_protocol_without_variables_is_rejected(client, admin_headers):
    """A trigger with nothing to evaluate is not a protocol [400]."""
    _assert_rejected(_upsert(client, admin_headers, []))


def test_an_item_protocol_requires_a_combination_variable(client, admin_headers):
    """An ITEM protocol alerts on a prescribed item, so it must describe one [400]."""
    response = _upsert(
        client,
        admin_headers,
        [_AGE_VARIABLE],
        protocol_type=ProtocolTypeEnum.PRESCRIPTION_ITEM.value,
    )

    _assert_rejected(response)


def test_an_item_protocol_with_a_combination_is_accepted(client, admin_headers):
    """The same protocol type passes once it carries a combination variable."""
    response = _upsert(
        client,
        admin_headers,
        [dict(_COMBINATION_VARIABLE)],
        protocol_type=ProtocolTypeEnum.PRESCRIPTION_ITEM.value,
    )

    assert response.status_code == status.HTTP_200_OK


@pytest.mark.parametrize(
    "protocol_type",
    [
        ProtocolTypeEnum.PRESCRIPTION_AGG.value,
        ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL.value,
        ProtocolTypeEnum.PRESCRIPTION_ALL.value,
    ],
)
def test_other_protocol_types_need_no_combination(
    client, admin_headers, protocol_type
):
    """The combination rule is specific to ITEM protocols, not a global one."""
    response = _upsert(
        client, admin_headers, [dict(_AGE_VARIABLE)], protocol_type=protocol_type
    )

    assert response.status_code == status.HTTP_200_OK


# --- name and field ------------------------------------------------------------


@pytest.mark.parametrize("name", [None, ""])
def test_a_variable_without_a_name_is_rejected(client, admin_headers, name):
    """The trigger refers to a variable by name, so an unnamed one is useless [400]."""
    _assert_rejected(
        _upsert(client, admin_headers, [{**_AGE_VARIABLE, "name": name}])
    )


@pytest.mark.parametrize("field", [None, ""])
def test_a_variable_without_a_field_is_rejected(client, admin_headers, field):
    """A criterion that names nothing to look at is rejected [400]."""
    _assert_rejected(
        _upsert(client, admin_headers, [{**_AGE_VARIABLE, "field": field}])
    )


def test_a_variable_with_an_unknown_field_is_rejected(client, admin_headers):
    """Only the fields of ProtocolVariableFieldEnum are evaluable [400]."""
    _assert_rejected(
        _upsert(client, admin_headers, [{**_AGE_VARIABLE, "field": "bloodType"}])
    )


# --- fields carrying their own required key ------------------------------------


def test_an_exam_variable_requires_an_exam_type(client, admin_headers):
    """``exam`` compares one specific exam: without naming it there is none [400]."""
    _assert_rejected(
        _upsert(
            client,
            admin_headers,
            [{"name": "v1", "field": "exam", "operator": ">", "value": "10"}],
        )
    )


def test_a_cn_stats_variable_requires_an_indicator(client, admin_headers):
    """``cn_stats`` compares one NoHarm Care indicator, which must be named [400]."""
    _assert_rejected(
        _upsert(
            client,
            admin_headers,
            [{"name": "v1", "field": "cn_stats", "operator": ">", "value": "0"}],
        )
    )


def test_an_empty_exam_period_is_dropped_from_the_stored_config(
    client, admin_headers
):
    """The editor sends ``examPeriod: ""`` when the field is left blank.

    An empty period is not a zero-day window: the key is removed so the
    evaluation falls back to its default instead of comparing against "".
    """
    response = _upsert(
        client,
        admin_headers,
        [
            {
                "name": "v1",
                "field": "exam",
                "examType": "ckd21",
                "examPeriod": "",
                "operator": ">",
                "value": "1",
            }
        ],
    )

    assert response.status_code == status.HTTP_200_OK
    assert "examPeriod" not in _stored_variables()[0]


def test_a_filled_exam_period_is_kept(client, admin_headers):
    """Only an empty period is dropped — a real one reaches the stored config."""
    response = _upsert(
        client,
        admin_headers,
        [
            {
                "name": "v1",
                "field": "exam",
                "examType": "ckd21",
                "examPeriod": "7",
                "operator": ">",
                "value": "1",
            }
        ],
    )

    assert response.status_code == status.HTTP_200_OK
    assert _stored_variables()[0]["examPeriod"] == "7"


# --- operator and value of a comparison ----------------------------------------


@pytest.mark.parametrize("operator", [None, ""])
def test_a_comparison_without_an_operator_is_rejected(
    client, admin_headers, operator
):
    """A field and a value with nothing comparing them is incomplete [400]."""
    _assert_rejected(
        _upsert(client, admin_headers, [{**_AGE_VARIABLE, "operator": operator}])
    )


@pytest.mark.parametrize("value", [None, "", []])
def test_a_comparison_without_a_value_is_rejected(client, admin_headers, value):
    """Null, blank and the empty list are all "nothing to compare against" [400]."""
    _assert_rejected(
        _upsert(client, admin_headers, [{**_AGE_VARIABLE, "value": value}])
    )


def test_zero_is_a_value_not_an_empty_field(client, admin_headers):
    """``"0"`` is a legitimate threshold and must not be read as blank.

    "> 0" is how a protocol expresses the presence of a result, so rejecting it
    as empty would make a whole class of triggers unwritable. The editor sends
    numbers as text, so the value arrives as the string "0".
    """
    response = _upsert(
        client, admin_headers, [{**_AGE_VARIABLE, "operator": ">", "value": "0"}]
    )

    assert response.status_code == status.HTTP_200_OK
    assert _stored_variables()[0]["value"] == "0"


def test_an_unknown_operator_is_rejected(client, admin_headers):
    """Only the operators the evaluator implements are accepted [400]."""
    _assert_rejected(
        _upsert(client, admin_headers, [{**_AGE_VARIABLE, "operator": "LIKE"}])
    )


@pytest.mark.parametrize(
    "operator", [">", "<", ">=", "<=", "=", "!=", "CONTAINS"]
)
def test_every_scalar_operator_is_accepted(client, admin_headers, operator):
    """The allowed scalar operators all pass validation."""
    response = _upsert(
        client, admin_headers, [{**_AGE_VARIABLE, "operator": operator}]
    )

    assert response.status_code == status.HTTP_200_OK


@pytest.mark.parametrize("operator", ["IN", "NOTIN"])
def test_a_set_operator_requires_a_list(client, admin_headers, operator):
    """``IN``/``NOTIN`` test membership, so a scalar value is a mistake [400]."""
    _assert_rejected(
        _upsert(
            client,
            admin_headers,
            [{**_ROUTE_VARIABLE, "operator": operator, "value": "IV"}],
        )
    )


@pytest.mark.parametrize("operator", ["IN", "NOTIN"])
def test_a_set_operator_with_a_list_is_accepted(client, admin_headers, operator):
    """The same operators pass once the value really is a list."""
    response = _upsert(
        client,
        admin_headers,
        [{**_ROUTE_VARIABLE, "operator": operator, "value": ["IV", "ORAL"]}],
    )

    assert response.status_code == status.HTTP_200_OK


def test_a_scalar_operator_rejects_a_list(client, admin_headers):
    """The mirror rule: a list compared with ``>`` is a mistake too [400]."""
    _assert_rejected(
        _upsert(
            client,
            admin_headers,
            [{**_AGE_VARIABLE, "operator": ">", "value": ["60", "70"]}],
        )
    )


# --- the combination variable --------------------------------------------------


def test_a_combination_is_exempt_from_the_operator_value_rules(
    client, admin_headers
):
    """A combination carries ids under their own keys, not an operator/value pair.

    It would fail the comparison rules outright, so validation takes the other
    branch for it entirely.
    """
    response = _upsert(
        client,
        admin_headers,
        [
            {
                "name": "v1",
                "field": "combination",
                "operator": "IN",
                "route": ["IV"],
                "dose": "10",
                "doseOperator": ">",
            }
        ],
    )

    assert response.status_code == status.HTTP_200_OK


def test_empty_combination_keys_are_dropped_from_the_stored_config(
    client, admin_headers
):
    """The editor renders every combination key, so most arrive empty.

    They are stripped rather than rejected: an empty ``dose`` means "do not
    filter by dose", and keeping it would narrow the match to the empty value.
    """
    response = _upsert(
        client,
        admin_headers,
        [
            {
                "name": "v1",
                "field": "combination",
                "operator": "IN",
                "route": ["IV"],
                "substance": [],
                "drug": [],
                "class": [],
                "dose": "",
                "doseOperator": "",
                "frequencyday": None,
                "period": "",
            }
        ],
    )

    assert response.status_code == status.HTTP_200_OK

    stored = _stored_variables()[0]
    for dropped in (
        "substance",
        "drug",
        "class",
        "dose",
        "doseOperator",
        "frequencyday",
        "period",
    ):
        assert dropped not in stored, f"{dropped} should have been dropped"
    # what was actually filled in survives
    assert stored["route"] == ["IV"]


def test_a_combination_rejects_an_invalid_inner_operator(client, admin_headers):
    """A filled ``*Operator`` key is still checked against the operator set [400]."""
    _assert_rejected(
        _upsert(
            client,
            admin_headers,
            [
                {
                    "name": "v1",
                    "field": "combination",
                    "operator": "IN",
                    "route": ["IV"],
                    "dose": "10",
                    "doseOperator": "LIKE",
                }
            ],
        )
    )


def test_a_combination_keeps_its_valid_inner_operators(client, admin_headers):
    """The inner operators of a filled criterion reach the stored config."""
    response = _upsert(
        client,
        admin_headers,
        [
            {
                "name": "v1",
                "field": "combination",
                "operator": "IN",
                "route": ["IV"],
                "dose": "10",
                "doseOperator": ">=",
                "period": "2",
                "periodOperator": "<=",
            }
        ],
    )

    assert response.status_code == status.HTTP_200_OK

    stored = _stored_variables()[0]
    assert stored["doseOperator"] == ">="
    assert stored["periodOperator"] == "<="


# --- the rules apply to every variable, not just the first ---------------------


def test_a_later_variable_is_validated_too(client, admin_headers):
    """Validation does not stop at the first well-formed criterion [400]."""
    _assert_rejected(
        _upsert(
            client,
            admin_headers,
            [
                dict(_AGE_VARIABLE),
                {"name": "v2", "field": "weight", "operator": "LIKE", "value": "80"},
            ],
            trigger="{{v1}} and {{v2}}",
        )
    )
