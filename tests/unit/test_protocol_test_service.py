"""Test: protocol test service (_evaluate_date_groups compact/full + type mapping)"""

from models.enums import ProtocolTypeEnum
from models.prescription import Patient, Prescription
from services.protocol_trace_service import (
    _evaluate_date_groups,
    _protocol_type_to_agg,
)
from tests.utils import utils_test_prescription


def _get_context(drug_list=None):
    """Builds the evaluation context dict with minimal mock data"""

    prescription = Prescription()
    prescription.idDepartment = 100

    return {
        "prescription": prescription,
        "patient": Patient(),
        "drug_list": drug_list if drug_list is not None else [],
        "exams": {},
        "cn_stats": {},
        "protocol_extra_info": None,
    }


def _folfox_drug_list():
    return [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=1,
            dose=10,
            drug_name="FLUOROURACIL",
            drug_class="Q1",
            sctid="FLUOROURACIL",
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=2,
            dose=20,
            drug_name="OXALIPLATINA",
            drug_class="Q1",
            sctid="OXALIPLATINA",
        ),
    ]


def _folfox_config(trigger="{{v1}} and {{v2}}"):
    return {
        "variables": [
            {
                "name": "v1",
                "field": "substance",
                "operator": "IN",
                "value": ["FLUOROURACIL"],
            },
            {
                "name": "v2",
                "field": "substance",
                "operator": "IN",
                "value": ["OXALIPLATINA"],
            },
        ],
        "trigger": trigger,
        "result": {"type": "SHOW_MESSAGE", "level": "high", "message": "FOLFOX"},
    }


def test_evaluate_date_groups_compact_activated():
    """Protocol test: compact groups expose only date/activated/summary"""

    drug_list = _folfox_drug_list()
    groups = _evaluate_date_groups(
        config=_folfox_config(),
        protocol_name="FOLFOX",
        context=_get_context(drug_list=drug_list),
        drugs_by_expire_date={"2026-07-31": drug_list},
        name_lookup=None,
        compact=True,
    )

    assert len(groups) == 1
    group = groups[0]
    assert group["date"] == "2026-07-31"
    assert group["activated"] is True
    assert "ATIVADO" in group["summary"]
    assert "trigger" not in group
    assert "variables" not in group
    assert "variableMessages" not in group


def test_evaluate_date_groups_compact_not_activated():
    """Protocol test: compact group reports non-activation"""

    drug_list = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=1,
            dose=10,
            drug_name="FLUOROURACIL",
            drug_class="Q1",
            sctid="FLUOROURACIL",
        ),
    ]

    groups = _evaluate_date_groups(
        config=_folfox_config(),
        protocol_name="FOLFOX",
        context=_get_context(drug_list=drug_list),
        drugs_by_expire_date={"2026-07-31": drug_list},
        name_lookup=None,
        compact=True,
    )

    assert groups[0]["activated"] is False
    assert "NÃO ativado" in groups[0]["summary"]


def test_evaluate_date_groups_full_matches_trace_shape():
    """Protocol test: full groups keep the existing trace endpoint shape"""

    drug_list = _folfox_drug_list()
    groups = _evaluate_date_groups(
        config=_folfox_config(),
        protocol_name="FOLFOX",
        context=_get_context(drug_list=drug_list),
        drugs_by_expire_date={"2026-07-31": drug_list},
        name_lookup={"substance": {}, "drug": {}},
        compact=False,
    )

    group = groups[0]
    assert group["activated"] is True
    assert group["trigger"] == {
        "expression": "{{v1}} and {{v2}}",
        "substituted": "True and True",
        "result": True,
    }
    assert group["result"] is not None
    assert isinstance(group["variableMessages"], list)
    assert isinstance(group["relatedItems"], list)
    assert len(group["variables"]) == 2
    assert group["variables"][0]["name"] == "v1"
    assert group["variables"][0]["result"] is True


def test_evaluate_date_groups_invalid_config():
    """Protocol test: invalid config becomes a per-group error, not an exception"""

    drug_list = _folfox_drug_list()
    groups = _evaluate_date_groups(
        config=_folfox_config(trigger="{{v1}} and __import__('os')"),
        protocol_name="FOLFOX",
        context=_get_context(drug_list=drug_list),
        drugs_by_expire_date={"2026-07-31": drug_list},
        name_lookup=None,
        compact=True,
    )

    assert groups[0]["date"] == "2026-07-31"
    assert "Configuração do protocolo inválida" in groups[0]["error"]
    assert "activated" not in groups[0]


def test_protocol_type_to_agg():
    """Protocol test: sampling targets individual prescriptions only for the
    individual protocol type; every other type runs on aggregated ones"""

    assert (
        _protocol_type_to_agg(ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL.value) is False
    )
    assert _protocol_type_to_agg(ProtocolTypeEnum.PRESCRIPTION_AGG.value) is True
    assert _protocol_type_to_agg(ProtocolTypeEnum.PRESCRIPTION_ALL.value) is True
    assert _protocol_type_to_agg(ProtocolTypeEnum.PRESCRIPTION_ITEM.value) is True
