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


def _single_substance_config(sctid: str, only_latest_expire_date=None):
    """Config activated by the presence of one substance, optionally restricted
    to the most recent expire date group"""

    config = {
        "variables": [
            {"name": "v1", "field": "substance", "operator": "IN", "value": [sctid]},
        ],
        "trigger": "{{v1}}",
        "result": {"type": "SHOW_MESSAGE", "level": "high", "message": "msg"},
    }

    if only_latest_expire_date is not None:
        config["onlyLatestExpireDate"] = only_latest_expire_date

    return config


def _two_date_groups():
    """Two expire date groups holding a different substance each"""

    return {
        "2026-07-30": [
            utils_test_prescription.get_prescription_drug_mock_row(
                id_prescription_drug=1,
                dose=10,
                drug_name="FLUOROURACIL",
                drug_class="Q1",
                sctid="FLUOROURACIL",
            )
        ],
        "2026-07-31": [
            utils_test_prescription.get_prescription_drug_mock_row(
                id_prescription_drug=2,
                dose=20,
                drug_name="OXALIPLATINA",
                drug_class="Q1",
                sctid="OXALIPLATINA",
            )
        ],
    }


def test_evaluate_date_groups_only_latest_expire_date():
    """onlyLatestExpireDate: the trace mirrors production and evaluates the
    newest group alone, so the older group is not reported at all"""

    groups = _evaluate_date_groups(
        config=_single_substance_config("OXALIPLATINA", only_latest_expire_date=True),
        protocol_name="Protocolo",
        context=_get_context(),
        drugs_by_expire_date=_two_date_groups(),
        name_lookup=None,
        compact=True,
    )

    assert [g["date"] for g in groups] == ["2026-07-31"]
    assert groups[0]["activated"] is True


def test_evaluate_date_groups_only_latest_expire_date_skips_older_match():
    """A protocol restricted to the newest group does not fire on an older one"""

    groups = _evaluate_date_groups(
        config=_single_substance_config("FLUOROURACIL", only_latest_expire_date=True),
        protocol_name="Protocolo",
        context=_get_context(),
        drugs_by_expire_date=_two_date_groups(),
        name_lookup=None,
        compact=True,
    )

    assert [g["date"] for g in groups] == ["2026-07-31"]
    assert groups[0]["activated"] is False


def test_evaluate_date_groups_without_the_flag_evaluates_every_group():
    """Back compatibility: a config without the key keeps every date group"""

    groups = _evaluate_date_groups(
        config=_single_substance_config("FLUOROURACIL"),
        protocol_name="Protocolo",
        context=_get_context(),
        drugs_by_expire_date=_two_date_groups(),
        name_lookup=None,
        compact=True,
    )

    assert [g["date"] for g in groups] == ["2026-07-30", "2026-07-31"]
    assert [g["activated"] for g in groups] == [True, False]


def test_evaluate_date_groups_only_latest_expire_date_without_groups():
    """A prescription with no date group yields no evaluation, not an error"""

    groups = _evaluate_date_groups(
        config=_single_substance_config("FLUOROURACIL", only_latest_expire_date=True),
        protocol_name="Protocolo",
        context=_get_context(),
        drugs_by_expire_date={},
        name_lookup=None,
        compact=True,
    )

    assert groups == []
