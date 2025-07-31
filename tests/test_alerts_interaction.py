from typing import List

from services.alert_interaction_service import find_relations
from tests.utils import utils_test_prescription


def _mock_get_allergies(data: List[dict]):
    def allergies(*args, **kwargs):
        # Simulate an allergy to Drug A

        return data

    return allergies


def _mock_get_active_relations(kind: str):
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
                "level": 1,
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
