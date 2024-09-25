from services.alert_interaction_service import find_relations

from conftest import get_mock_row


def _mock_get_allergies(*args, **kwargs):
    # Simulate an allergy to Drug A

    return []

    """
    return [
        type(
            "obj",
            (object,),
            {
                "idDrug": "1",
                "idPatient": "1",
                "drugName": "Drug A Substance",
                "active": True,
                "createdAt": datetime.now(),
            },
        )
    ]
    """


def _mock_get_active_relations_kind_it(*args, **kwargs):
    # Simulate the response from the database
    active_relations = {}
    # Example mock data that mimics the database response
    mock_data = [
        {
            "sctida": "211111",
            "sctidb": "111111",
            "kind": "it",
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


def _mock_get_active_relations_kind_dt(*args, **kwargs):
    # Simulate the response from the database
    active_relations = {}
    # Example mock data that mimics the database response
    mock_data = [
        {
            "sctida": "211111",
            "sctidb": "111111",
            "kind": "dt",
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


def _mock_get_active_relations_kind_dm(*args, **kwargs):
    # Simulate the response from the database
    active_relations = {}
    # Example mock data that mimics the database response
    mock_data = [
        {
            "sctida": "211111",
            "sctidb": "111111",
            "kind": "dm",
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


def _mock_get_active_relations_kind_iy(*args, **kwargs):
    # Simulate the response from the database
    active_relations = {}
    # Example mock data that mimics the database response
    mock_data = [
        {
            "sctida": "211111",
            "sctidb": "111111",
            "kind": "iy",
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


def _mock_get_active_relations_kind_sl(*args, **kwargs):
    # Simulate the response from the database
    active_relations = {}
    # Example mock data that mimics the database response
    mock_data = [
        {
            "sctida": "211111",
            "sctidb": "111111",
            "kind": "sl",
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


def test_find_relations_drug_interaction_kind_it(monkeypatch):
    """Alertas interação: Testa interação medicamentosa"""

    drug_list = [
        get_mock_row(id_prescription_drug=1, dose=10, drug_name="Drug A"),
        get_mock_row(id_prescription_drug=2, dose=20, drug_name="Drug B"),
        get_mock_row(id_prescription_drug=3, dose=20, drug_name="Drug C"),
    ]

    monkeypatch.setattr(
        "services.alert_interaction_service._get_allergies", _mock_get_allergies
    )
    monkeypatch.setattr(
        "services.alert_interaction_service._get_active_relations",
        _mock_get_active_relations_kind_it,
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
    assert (
        alert_2["text"]
        == "Interação Medicamentosa: Drug A interacts with Drug B (Drug B e Drug A)"
    )

    # Assert alert details for idPrescriptionDrug '1'
    alert_1 = results["alerts"]["1"][0]
    assert alert_1["idPrescriptionDrug"] == "1"
    assert alert_1["key"] == "211111-111111-it"
    assert alert_1["type"] == "it"
    assert alert_1["level"] == 1
    assert alert_1["relation"] == "1"
    assert (
        alert_1["text"]
        == "Interação Medicamentosa: Drug A interacts with Drug B (Drug B e Drug A)"
    )

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
        get_mock_row(id_prescription_drug=1, dose=10, drug_name="Drug A"),
        get_mock_row(id_prescription_drug=2, dose=20, drug_name="Drug B"),
        get_mock_row(id_prescription_drug=3, dose=20, drug_name="Drug C"),
    ]

    monkeypatch.setattr(
        "services.alert_interaction_service._get_allergies", _mock_get_allergies
    )
    monkeypatch.setattr(
        "services.alert_interaction_service._get_active_relations",
        _mock_get_active_relations_kind_dt,
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
        get_mock_row(id_prescription_drug=1, dose=10, drug_name="Drug A"),
        get_mock_row(id_prescription_drug=2, dose=20, drug_name="Drug B"),
        get_mock_row(id_prescription_drug=3, dose=20, drug_name="Drug C"),
    ]

    monkeypatch.setattr(
        "services.alert_interaction_service._get_allergies", _mock_get_allergies
    )
    monkeypatch.setattr(
        "services.alert_interaction_service._get_active_relations",
        _mock_get_active_relations_kind_dm,
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
        get_mock_row(
            id_prescription_drug=1, dose=10, drug_name="Drug A", intravenous=True
        ),
        get_mock_row(
            id_prescription_drug=2, dose=20, drug_name="Drug B", intravenous=True
        ),
        get_mock_row(
            id_prescription_drug=3, dose=20, drug_name="Drug C", intravenous=True
        ),
    ]

    monkeypatch.setattr(
        "services.alert_interaction_service._get_allergies", _mock_get_allergies
    )
    monkeypatch.setattr(
        "services.alert_interaction_service._get_active_relations",
        _mock_get_active_relations_kind_iy,
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

    assert (
        alert_2["text"]
        == "Incompatibilidade em Y: Drug A interacts with Drug B (Drug B e Drug A)"
    )

    # Assert alert details for idPrescriptionDrug '1'
    alert_1 = results["alerts"]["1"][0]
    assert alert_1["idPrescriptionDrug"] == "1"
    assert alert_1["key"] == "211111-111111-iy"
    assert alert_1["type"] == "iy"
    assert alert_1["level"] == 1
    assert alert_1["relation"] == "1"

    assert (
        alert_1["text"]
        == "Incompatibilidade em Y: Drug A interacts with Drug B (Drug B e Drug A)"
    )

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
        get_mock_row(
            id_prescription_drug=1,
            dose=10,
            drug_name="Drug A",
            group="1",
            solutionGroup=True,
            idPrescription="111",
        ),
        get_mock_row(
            id_prescription_drug=2,
            dose=20,
            drug_name="Drug B",
            group="1",
            solutionGroup=True,
            idPrescription="111",
        ),
        get_mock_row(
            id_prescription_drug=3,
            dose=20,
            drug_name="Drug C",
            group="1",
            solutionGroup=True,
            idPrescription="222",
        ),
    ]

    monkeypatch.setattr(
        "services.alert_interaction_service._get_allergies", _mock_get_allergies
    )
    monkeypatch.setattr(
        "services.alert_interaction_service._get_active_relations",
        _mock_get_active_relations_kind_sl,
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
