from collections import namedtuple
from typing import List

import pytest

from services.alert_interaction_service import (
    _get_allergies,
    _to_array_literal,
    find_relations,
)
from tests.utils import utils_test_prescription


def _mock_get_allergies(data: List[dict]):
    def allergies(*args, **kwargs):
        # Simulate an allergy to Drug A

        return data

    return allergies


def _mock_get_active_relations(kind: str, level=1):
    def mock(*args, **kwargs):
        # Simulate the response from the database
        active_relations = {}
        # Example mock data that mimics the database response
        mock_data = [
            {
                "sctida": "211111",
                "sctidb": "111111",
                "kind": kind,
                "text": "Drug A interacts with Drug B",
                "level": level,
            },
        ]

        for item in mock_data:
            key = f"{item['sctida']}-{item['sctidb']}-{item['kind']}"
            active_relations[key] = {
                "sctida": item["sctida"],
                "sctidb": item["sctidb"],
                "kind": item["kind"],
                "text": item["text"],
                "level": item["level"],
            }

        return active_relations

    return mock


def test_find_relations_drug_interaction_kind_it(monkeypatch):
    """Alertas interação: Testa interação medicamentosa"""

    drug_list = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=1, dose=10, drug_name="Drug A"
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=2, dose=20, drug_name="Drug B"
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=3, dose=20, drug_name="Drug C"
        ),
    ]

    monkeypatch.setattr(
        "services.alert_interaction_service._get_allergies",
        _mock_get_allergies(data=[]),
    )
    monkeypatch.setattr(
        "services.alert_interaction_service._get_active_relations",
        _mock_get_active_relations(kind="it"),
    )

    results = find_relations(drug_list, id_patient=1, is_cpoe=False)

    # Assert alerts structure
    assert "alerts" in results
    assert "2" in results["alerts"]
    assert "1" in results["alerts"]

    # Assert alert details for idPrescriptionDrug '2'
    alert_2 = results["alerts"]["2"][0]
    assert alert_2["idPrescriptionDrug"] == "2"
    assert alert_2["key"] == "211111-111111-it"
    assert alert_2["type"] == "it"
    assert alert_2["level"] == 1
    assert alert_2["relation"] == "1"

    assert "Interação Medicamentosa: Drug A interacts with Drug B" in alert_2["text"]

    # Assert alert details for idPrescriptionDrug '1'
    alert_1 = results["alerts"]["1"][0]
    assert alert_1["idPrescriptionDrug"] == "1"
    assert alert_1["key"] == "211111-111111-it"
    assert alert_1["type"] == "it"
    assert alert_1["level"] == 1
    assert alert_1["relation"] == "1"

    assert "Interação Medicamentosa: Drug A interacts with Drug B" in alert_1["text"]

    # Assert stats structure
    assert "stats" in results
    assert results["stats"]["it"] == 1
    assert results["stats"]["dt"] == 0
    assert results["stats"]["dm"] == 0
    assert results["stats"]["iy"] == 0
    assert results["stats"]["sl"] == 0
    assert results["stats"]["rx"] == 0


def test_find_relations_drug_interaction_kind_dt(monkeypatch):
    """Alertas interação: Testa interação medicamentosa"""

    drug_list = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=1, dose=10, drug_name="Drug A"
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=2, dose=20, drug_name="Drug B"
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=3, dose=20, drug_name="Drug C"
        ),
    ]

    monkeypatch.setattr(
        "services.alert_interaction_service._get_allergies",
        _mock_get_allergies(data=[]),
    )
    monkeypatch.setattr(
        "services.alert_interaction_service._get_active_relations",
        _mock_get_active_relations(kind="dt"),
    )

    results = find_relations(drug_list, id_patient=1, is_cpoe=False)

    # Assert alerts structure
    assert "alerts" in results
    assert "2" in results["alerts"]
    assert "1" in results["alerts"]

    # Assert alert details for idPrescriptionDrug '2'
    alert_2 = results["alerts"]["2"][0]
    assert alert_2["idPrescriptionDrug"] == "2"
    assert alert_2["key"] == "211111-111111-dt"
    assert alert_2["type"] == "dt"
    assert alert_2["level"] == 1
    assert alert_2["relation"] == "1"

    assert (
        alert_2["text"]
        == "Duplicidade Terapêutica: Drug A interacts with Drug B (Drug B e Drug A)"
    )

    # Assert alert details for idPrescriptionDrug '1'
    alert_1 = results["alerts"]["1"][0]
    assert alert_1["idPrescriptionDrug"] == "1"
    assert alert_1["key"] == "211111-111111-dt"
    assert alert_1["type"] == "dt"
    assert alert_1["level"] == 1
    assert alert_1["relation"] == "1"

    assert (
        alert_1["text"]
        == "Duplicidade Terapêutica: Drug A interacts with Drug B (Drug B e Drug A)"
    )

    # Assert stats structure
    assert "stats" in results
    assert results["stats"]["it"] == 0
    assert results["stats"]["dt"] == 1
    assert results["stats"]["dm"] == 0
    assert results["stats"]["iy"] == 0
    assert results["stats"]["sl"] == 0
    assert results["stats"]["rx"] == 0


def test_find_relations_drug_interaction_kind_dm(monkeypatch):
    """Alertas interação: Testa interação medicamentosa"""

    drug_list = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=1, dose=10, drug_name="Drug A"
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=2, dose=20, drug_name="Drug B"
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=3, dose=20, drug_name="Drug C"
        ),
    ]

    monkeypatch.setattr(
        "services.alert_interaction_service._get_allergies",
        _mock_get_allergies(data=[]),
    )
    monkeypatch.setattr(
        "services.alert_interaction_service._get_active_relations",
        _mock_get_active_relations(kind="dm"),
    )

    results = find_relations(drug_list, id_patient=1, is_cpoe=False)

    # Assert alerts structure
    assert "alerts" in results
    assert "2" in results["alerts"]
    # assert "1" in results["alerts"]

    # Assert alert details for idPrescriptionDrug '2'
    alert_2 = results["alerts"]["2"][0]
    assert alert_2["idPrescriptionDrug"] == "2"
    assert alert_2["key"] == "211111-111111-dm"
    assert alert_2["type"] == "dm"
    assert alert_2["level"] == 1
    assert alert_2["relation"] == "1"

    assert (
        alert_2["text"]
        == "Duplicidade Medicamentosa: Drug A interacts with Drug B (Drug B e Drug A)"
    )

    # Assert stats structure
    assert "stats" in results
    assert results["stats"]["it"] == 0
    assert results["stats"]["dt"] == 0
    assert results["stats"]["dm"] == 1
    assert results["stats"]["iy"] == 0
    assert results["stats"]["sl"] == 0
    assert results["stats"]["rx"] == 0


def test_find_relations_drug_interaction_kind_iy(monkeypatch):
    """Alertas interação: Testa interação medicamentosa"""

    drug_list = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=1, dose=10, drug_name="Drug A", intravenous=True
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=2, dose=20, drug_name="Drug B", intravenous=True
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=3, dose=20, drug_name="Drug C", intravenous=True
        ),
    ]

    monkeypatch.setattr(
        "services.alert_interaction_service._get_allergies",
        _mock_get_allergies(data=[]),
    )
    monkeypatch.setattr(
        "services.alert_interaction_service._get_active_relations",
        _mock_get_active_relations(kind="iy"),
    )

    results = find_relations(drug_list, id_patient=1, is_cpoe=False)

    # Assert alerts structure
    assert "alerts" in results
    assert "2" in results["alerts"]
    assert "1" in results["alerts"]

    # Assert alert details for idPrescriptionDrug '2'
    alert_2 = results["alerts"]["2"][0]
    assert alert_2["idPrescriptionDrug"] == "2"
    assert alert_2["key"] == "211111-111111-iy"
    assert alert_2["type"] == "iy"
    assert alert_2["level"] == 1
    assert alert_2["relation"] == "1"

    assert "Incompatibilidade em Y: Drug A interacts with Drug B" in alert_2["text"]

    # Assert alert details for idPrescriptionDrug '1'
    alert_1 = results["alerts"]["1"][0]
    assert alert_1["idPrescriptionDrug"] == "1"
    assert alert_1["key"] == "211111-111111-iy"
    assert alert_1["type"] == "iy"
    assert alert_1["level"] == 1
    assert alert_1["relation"] == "1"

    assert "Incompatibilidade em Y: Drug A interacts with Drug B" in alert_1["text"]

    # Assert stats structure
    assert "stats" in results
    assert results["stats"]["it"] == 0
    assert results["stats"]["dt"] == 0
    assert results["stats"]["dm"] == 0
    assert results["stats"]["iy"] == 1
    assert results["stats"]["sl"] == 0
    assert results["stats"]["rx"] == 0


def test_find_relations_drug_interaction_kind_sl(monkeypatch):
    """Alertas interação: Testa interação medicamentosa"""

    drug_list = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=1,
            dose=10,
            drug_name="Drug A",
            group="1",
            solutionGroup="99",
            idPrescription="111",
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=2,
            dose=20,
            drug_name="Drug B",
            group="1",
            solutionGroup="99",
            idPrescription="111",
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=3,
            dose=20,
            drug_name="Drug C",
            group="1",
            solutionGroup="99",
            idPrescription="222",
        ),
    ]

    monkeypatch.setattr(
        "services.alert_interaction_service._get_allergies",
        _mock_get_allergies(data=[]),
    )
    monkeypatch.setattr(
        "services.alert_interaction_service._get_active_relations",
        _mock_get_active_relations(kind="sl"),
    )

    results = find_relations(drug_list, id_patient=1, is_cpoe=False)
    # Assert alerts structure
    assert "alerts" in results
    assert "2" in results["alerts"]
    assert "1" in results["alerts"]

    # Assert alert details for idPrescriptionDrug '2'
    alert_2 = results["alerts"]["2"][0]
    assert alert_2["idPrescriptionDrug"] == "2"
    assert alert_2["key"] == "211111-111111-sl"
    assert alert_2["type"] == "sl"
    assert alert_2["level"] == 1
    assert alert_2["relation"] == "1"

    assert (
        alert_2["text"]
        == "ISL Incompatibilidade em Solução: Drug A interacts with Drug B (Drug B e Drug A)"
    )

    # Assert alert details for idPrescriptionDrug '1'
    alert_1 = results["alerts"]["1"][0]
    assert alert_1["idPrescriptionDrug"] == "1"
    assert alert_1["key"] == "211111-111111-sl"
    assert alert_1["type"] == "sl"
    assert alert_1["level"] == 1
    assert alert_1["relation"] == "1"

    assert (
        alert_1["text"]
        == "ISL Incompatibilidade em Solução: Drug A interacts with Drug B (Drug B e Drug A)"
    )

    # Assert stats structure
    assert "stats" in results
    assert results["stats"]["it"] == 0
    assert results["stats"]["dt"] == 0
    assert results["stats"]["dm"] == 0
    assert results["stats"]["iy"] == 0
    assert results["stats"]["sl"] == 1
    assert results["stats"]["rx"] == 0


def test_find_relations_drug_interaction_kind_rx(monkeypatch):
    """Alertas interação: Testa reatividade cruzada"""

    drug_list = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=2,
            dose=10,
            drug_name="Drug A",
            group=None,
            solutionGroup=True,
            idPrescription="111",
        ),
    ]

    monkeypatch.setattr(
        "services.alert_interaction_service._get_allergies",
        _mock_get_allergies(
            data=[
                {
                    "id": None,
                    "drug": "Drug test RX",
                    "sctid": "111111",
                    "intravenous": False,
                    "group": None,
                    "frequency": None,
                    "rx": True,
                }
            ]
        ),
    )
    monkeypatch.setattr(
        "services.alert_interaction_service._get_active_relations",
        _mock_get_active_relations(kind="rx"),
    )

    results = find_relations(drug_list, id_patient=1, is_cpoe=False)
    # Assert alerts structure
    assert "alerts" in results
    assert "2" in results["alerts"]

    # Assert alert details for idPrescriptionDrug '2'
    alert_2 = results["alerts"]["2"][0]
    assert alert_2["idPrescriptionDrug"] == "2"
    assert alert_2["key"] == "211111-111111-rx"
    assert alert_2["type"] == "rx"
    assert alert_2["level"] == 1
    assert alert_2["relation"] == None

    assert (
        alert_2["text"]
        == "Reatividade Cruzada: Drug A interacts with Drug B (Drug A e Drug test RX)"
    )

    # Assert stats structure
    assert "stats" in results
    assert results["stats"]["it"] == 0
    assert results["stats"]["dt"] == 0
    assert results["stats"]["dm"] == 0
    assert results["stats"]["iy"] == 0
    assert results["stats"]["sl"] == 0
    assert results["stats"]["rx"] == 1


def test_find_relations_drug_interaction_kind_dm_freq_now(monkeypatch):
    """Alertas interação: Testa interação medicamentosa tipo DM com frequencia AGORA"""

    drug_list = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=1, dose=10, drug_name="Drug A", frequency=66
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=2, dose=20, drug_name="Drug B"
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=3, dose=20, drug_name="Drug C"
        ),
    ]

    monkeypatch.setattr(
        "services.alert_interaction_service._get_allergies",
        _mock_get_allergies(data=[]),
    )
    monkeypatch.setattr(
        "services.alert_interaction_service._get_active_relations",
        _mock_get_active_relations(kind="dm"),
    )

    results = find_relations(drug_list, id_patient=1, is_cpoe=False)

    # Assert alerts structure
    assert "alerts" in results
    assert 0 == len(results["alerts"])

    # Assert stats structure
    assert "stats" in results
    assert results["stats"]["it"] == 0
    assert results["stats"]["dt"] == 0
    assert results["stats"]["dm"] == 0
    assert results["stats"]["iy"] == 0
    assert results["stats"]["sl"] == 0
    assert results["stats"]["rx"] == 0


@pytest.mark.parametrize(
    "configured_level,expected_level",
    [
        ("high", "medium"),
        ("medium", "low"),
        ("low", "low"),
        (None, "low"),
    ],
)
def test_find_relations_drug_interaction_kind_dm_freq_sn(
    monkeypatch, configured_level, expected_level
):
    """Alertas interação: Testa redução de nível na interação tipo DM com frequencia SN"""

    drug_list = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=1, dose=10, drug_name="Drug A", frequency=33
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=2, dose=20, drug_name="Drug B"
        ),
    ]

    monkeypatch.setattr(
        "services.alert_interaction_service._get_allergies",
        _mock_get_allergies(data=[]),
    )
    monkeypatch.setattr(
        "services.alert_interaction_service._get_active_relations",
        _mock_get_active_relations(kind="dm", level=configured_level),
    )

    results = find_relations(drug_list, id_patient=1, is_cpoe=False)

    assert results["alerts"]["2"][0]["type"] == "dm"
    assert results["alerts"]["2"][0]["level"] == expected_level
    assert results["stats"]["dm"] == 1


def test_find_relations_drug_interaction_kind_dt_freq_sn_keeps_level(monkeypatch):
    """Alertas interação: Testa que frequencia SN não reduz nível fora do tipo DM"""

    drug_list = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=1, dose=10, drug_name="Drug A", frequency=33
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=2, dose=20, drug_name="Drug B"
        ),
    ]

    monkeypatch.setattr(
        "services.alert_interaction_service._get_allergies",
        _mock_get_allergies(data=[]),
    )
    monkeypatch.setattr(
        "services.alert_interaction_service._get_active_relations",
        _mock_get_active_relations(kind="dt", level="high"),
    )

    results = find_relations(drug_list, id_patient=1, is_cpoe=False)

    assert results["alerts"]["2"][0]["level"] == "high"


def _relation_item(**overrides) -> dict:
    """Comparable item as built by build_relation_item"""
    item = {
        "id": "1",
        "drug": "Drug A",
        "sctid": "111111",
        "intravenous": False,
        "group": None,
        "prescriptionDate": "2026-01-01T08:00:00",
        "expireDate": "2026-01-02T08:00:00",
        "frequency": 1,
        "rx": False,
        "interval": None,
    }
    item.update(overrides)
    return item


def test_evaluate_kind_rules_reports_every_rule():
    """Alertas interação: trace lista todas as regras do tipo, não só a primeira"""
    from services.alert_interaction_service import evaluate_kind_rules

    rules = evaluate_kind_rules(
        kind="dm",
        drug_from=_relation_item(frequency=66),
        drug_to=_relation_item(id="2", drug="Drug B", expireDate="2026-01-01T07:00:00"),
    )

    assert {r["rule"]: r["passed"] for r in rules} == {
        "not_allergy": True,
        "not_now_frequency": False,
        "time_overlap": True,
    }


def test_build_alert_explains_level_adjustments():
    """Alertas interação: ajustes de nível são explicados"""
    from services.alert_interaction_service import build_alert

    alert = build_alert(
        kind="dm",
        relation={"text": "texto", "level": "high"},
        drug_from=_relation_item(frequency=33),
        drug_to=_relation_item(id="2", drug="Drug B"),
    )

    assert alert["level"] == "medium"
    assert alert["ids"] == ["1"]
    assert len(alert["level_notes"]) == 1


# --- the patient's allergies, resolved from the allergy records -----------------

# the fields of allergy_repository.get_allergy_records that _get_allergies reads
_AllergyRecord = namedtuple("_AllergyRecord", "sctid drugSctid active substance")


def _fail_on_read(*args, **kwargs):
    """Stands in for the repository read where it must not happen"""
    raise AssertionError("the allergy records were given: they must not be read again")


def _allergy_sctids(records: list) -> list:
    """The substances the records resolve to as active allergies"""
    return [a["sctid"] for a in _get_allergies(id_patient=1, allergy_records=records)]


def test_allergies_come_from_the_records_given(monkeypatch):
    """Alertas interação: alergias resolvidas dos registros já lidos, sem nova consulta"""
    monkeypatch.setattr(
        "repository.allergy_repository.get_allergy_records", _fail_on_read
    )

    allergies = _get_allergies(
        id_patient=1,
        allergy_records=[
            _AllergyRecord(
                sctid=90302, drugSctid=None, active=True, substance="Substância B"
            )
        ],
    )

    assert allergies == [
        {
            "id": None,
            "drug": "Substância B",
            "sctid": 90302,
            "intravenous": False,
            "group": None,
            "frequency": None,
            "rx": True,
            "interval": "-",
        }
    ]


def test_allergies_are_read_when_no_records_are_given(monkeypatch):
    """Alertas interação: sem os registros, a função os consulta"""
    read = []

    def records_of(id_patient):
        """The repository read, noting which patient was asked for"""
        read.append(id_patient)
        return [_AllergyRecord(sctid=90301, drugSctid=None, active=True, substance="A")]

    monkeypatch.setattr("repository.allergy_repository.get_allergy_records", records_of)

    assert [a["sctid"] for a in _get_allergies(id_patient=7)] == [90301]
    assert read == [7]


def test_the_record_sctid_comes_before_the_substance_of_its_drug():
    """Alertas interação: o sctid do registro prevalece sobre o do medicamento"""
    assert _allergy_sctids(
        [_AllergyRecord(sctid=90301, drugSctid=90302, active=True, substance="A")]
    ) == [90301]

    assert _allergy_sctids(
        [_AllergyRecord(sctid=None, drugSctid=90302, active=True, substance="B")]
    ) == [90302]


@pytest.mark.parametrize(
    "record",
    [
        _AllergyRecord(sctid=90301, drugSctid=None, active=False, substance="A"),
        _AllergyRecord(sctid=90301, drugSctid=None, active=None, substance="A"),
        # an sctid that is not a substance (or a drug with none) resolves no name
        _AllergyRecord(sctid=90301, drugSctid=None, active=True, substance=None),
        _AllergyRecord(sctid=None, drugSctid=None, active=True, substance=None),
    ],
    ids=["inactive", "active_unknown", "sctid_not_a_substance", "no_substance"],
)
def test_records_that_are_not_an_active_allergy_to_a_substance_are_left_out(record):
    """Alertas interação: só alergia ativa com substância entra na reatividade cruzada"""
    assert _allergy_sctids([record]) == []


def test_each_substance_is_listed_once_ordered_by_sctid():
    """Alertas interação: uma entrada por substância, em ordem estável"""
    records = [
        _AllergyRecord(sctid=90303, drugSctid=None, active=True, substance="C"),
        _AllergyRecord(sctid=None, drugSctid=90301, active=True, substance="A"),
        _AllergyRecord(sctid=90303, drugSctid=90301, active=True, substance="C"),
        _AllergyRecord(sctid=90301, drugSctid=None, active=False, substance="A"),
    ]

    assert _allergy_sctids(records) == [90301, 90303]


def test_find_relations_uses_the_allergy_records_given(monkeypatch):
    """Alertas interação: a reatividade cruzada lê os registros recebidos"""
    monkeypatch.setattr(
        "repository.allergy_repository.get_allergy_records", _fail_on_read
    )
    monkeypatch.setattr(
        "services.alert_interaction_service._get_active_relations",
        _mock_get_active_relations(kind="rx"),
    )

    drug_list = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=2, dose=10, drug_name="Drug A"
        ),
    ]

    results = find_relations(
        drug_list,
        id_patient=1,
        is_cpoe=False,
        allergy_records=[
            _AllergyRecord(
                sctid="111111", drugSctid=None, active=True, substance="Drug test RX"
            )
        ],
    )

    assert results["stats"]["rx"] == 1
    assert results["alerts"]["2"][0]["key"] == "211111-111111-rx"


# --- the pairs sent to the relation query ---------------------------------------


def test_each_substance_pair_is_asked_once(monkeypatch):
    """Alertas interação: pares de substância repetidos são consultados uma vez"""
    asked = []

    def active_relations(pairs):
        """The relation query, noting the pairs it was asked for"""
        asked.append(pairs)
        return {}

    monkeypatch.setattr(
        "services.alert_interaction_service._get_allergies",
        _mock_get_allergies(data=[]),
    )
    monkeypatch.setattr(
        "services.alert_interaction_service._get_active_relations", active_relations
    )

    # the same two substances prescribed twice each: 12 ordered item pairs
    drug_list = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=id_prescription_drug, dose=10, sctid=sctid
        )
        for id_prescription_drug, sctid in [(1, 501), (2, 502), (3, 501), (4, 502)]
    ]

    find_relations(drug_list, id_patient=1, is_cpoe=False)

    assert len(asked) == 1
    assert asked[0] == [(501, 502), (501, 501), (502, 501), (502, 502)]


def test_a_repeated_alert_text_is_listed_once_per_item(monkeypatch):
    """Alertas interação: o mesmo texto não se repete no item"""
    monkeypatch.setattr(
        "services.alert_interaction_service._get_allergies",
        _mock_get_allergies(data=[]),
    )
    monkeypatch.setattr(
        "services.alert_interaction_service._get_active_relations",
        _mock_get_active_relations(kind="it"),
    )

    # item 2 interacts with items 1 and 3, which are the same drug: one text
    drug_list = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=id_prescription_drug,
            dose=10,
            drug_name=name,
            sctid=sctid,
        )
        for id_prescription_drug, name, sctid in [
            (1, "Drug B", "111111"),
            (2, "Drug A", "211111"),
            (3, "Drug B", "111111"),
        ]
    ]

    results = find_relations(drug_list, id_patient=1, is_cpoe=False)

    assert len(results["alerts"]["2"]) == 1
    assert results["stats"]["it"] == 1


def test_ids_go_to_the_query_as_an_array_literal():
    """Alertas interação: ids enviados como um literal de array do PostgreSQL"""
    assert _to_array_literal([900001, 900002]) == "{900001,900002}"
    assert _to_array_literal(iter([5])) == "{5}"
    assert _to_array_literal([]) == "{}"

    # only integer ids make it into the literal
    with pytest.raises(ValueError):
        _to_array_literal(["1},{2"])
