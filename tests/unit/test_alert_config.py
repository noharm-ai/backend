"""Section `alerts` of the schema params: the rules it adds to the interaction
alerts and the alert types it turns off (reading the item is tested in
test_schema_params.py)"""

import pytest

from models.alert_config import AlertConfig
from models.enums import FrequencyEnum
from services.alert_interaction_service import evaluate_kind_rules, find_relations
from tests.utils import utils_test_prescription

SN = FrequencyEnum.SN.value
ACM = FrequencyEnum.ACM.value


# --- rules -----------------------------------------------------------------


def _relation_item(**overrides) -> dict:
    """Comparable item as built by build_relation_item"""
    item = {
        "id": "1",
        "drug": "Drug A",
        "sctid": "111111",
        "intravenous": True,
        "group": None,
        "prescriptionDate": "2026-01-01T08:00:00",
        "expireDate": "2026-01-02T08:00:00",
        "frequency": 2,
        "rx": False,
        "interval": "08:00 20:00",
    }
    item.update(overrides)
    return item


def _config(**kinds) -> AlertConfig:
    return AlertConfig.model_validate({"interactions": kinds})


def _rules(kind, drug_from, drug_to, alert_config) -> dict:
    return {
        r["rule"]: r["passed"]
        for r in evaluate_kind_rules(
            kind=kind, drug_from=drug_from, drug_to=drug_to, alert_config=alert_config
        )
    }


def test_rules_without_config_are_unchanged():
    """Sem config, nenhuma regra nova aparece"""
    for alert_config in (None, AlertConfig()):
        rules = _rules(
            "iy", _relation_item(), _relation_item(id="2"), alert_config=alert_config
        )
        assert not any(r.startswith("config_") for r in rules)


@pytest.mark.parametrize(
    "freq_from,freq_to,passed",
    [(2, 2, True), (SN, 2, False), (2, ACM, False), (None, 2, True)],
)
def test_ignored_frequency_rule(freq_from, freq_to, passed):
    """Frequência configurada (de qualquer um dos itens) esconde o alerta"""
    rules = _rules(
        "iy",
        _relation_item(frequency=freq_from),
        _relation_item(id="2", frequency=freq_to),
        alert_config=_config(iy={"ignoreFrequencies": [SN, ACM]}),
    )

    assert rules["config_ignored_frequency"] is passed


def test_ignored_frequency_is_per_kind():
    """A config de um tipo não vale para os outros"""
    rules = _rules(
        "it",
        _relation_item(frequency=SN),
        _relation_item(id="2"),
        alert_config=_config(iy={"ignoreFrequencies": [SN]}),
    )

    assert "config_ignored_frequency" not in rules


def test_ignored_frequency_does_not_apply_to_rx():
    """Reatividade cruzada (alergia) não usa frequência"""
    rules = _rules(
        "rx",
        _relation_item(frequency=SN, rx=True),
        _relation_item(id=None, frequency=None, rx=True),
        alert_config=_config(rx={"ignoreFrequencies": [SN]}),
    )

    assert "config_ignored_frequency" not in rules


@pytest.mark.parametrize(
    "interval_from,interval_to,passed",
    [
        ("08:00 20:00", "08:00", True),
        ("08:00 20:00", "14:00", False),
        (None, "08:00", False),
        ("ACM", "ACM", False),
    ],
)
def test_interval_intersection_rule(interval_from, interval_to, passed):
    """iy só com horário de administração em comum"""
    rules = _rules(
        "iy",
        _relation_item(interval=interval_from),
        _relation_item(id="2", interval=interval_to),
        alert_config=_config(iy={"requireIntervalIntersection": True}),
    )

    assert rules["config_interval_intersection"] is passed


def test_interval_intersection_only_for_iy():
    """requireIntervalIntersection só vale para iy"""
    rules = _rules(
        "it",
        _relation_item(interval="08:00"),
        _relation_item(id="2", interval="14:00"),
        alert_config=_config(it={"requireIntervalIntersection": True}),
    )

    assert "config_interval_intersection" not in rules


def test_frequency_rule_message_names_the_frequency():
    """A mensagem (trace) mostra a frequência pelo nome"""
    rules = evaluate_kind_rules(
        kind="iy",
        drug_from=_relation_item(frequency=33.0),
        drug_to=_relation_item(id="2", drug="Drug B", frequency=33.5),
        alert_config=_config(iy={"ignoreFrequencies": [SN]}),
    )
    message = next(r for r in rules if r["rule"] == "config_ignored_frequency")[
        "message"
    ]

    assert "Configuração da instituição" in message
    assert "Drug A: SN (33)" in message
    assert "Drug B: 33.5" in message


# --- find_relations --------------------------------------------------------


def _mock_relations(kind: str):
    def mock(*args, **kwargs):
        return {
            f"211111-111111-{kind}": {
                "sctida": "211111",
                "sctidb": "111111",
                "kind": kind,
                "text": "Drug A interacts with Drug B",
                "level": "low",
            }
        }

    return mock


def _iy_drug_list(frequency_b=None, interval_a=None, interval_b=None):
    return [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=1,
            dose=10,
            drug_name="Drug A",
            intravenous=True,
            interval=interval_a,
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=2,
            dose=20,
            drug_name="Drug B",
            intravenous=True,
            frequency=frequency_b,
            interval=interval_b,
        ),
    ]


@pytest.fixture
def iy_relation(monkeypatch):
    monkeypatch.setattr(
        "services.alert_interaction_service._get_allergies", lambda **kw: []
    )
    monkeypatch.setattr(
        "services.alert_interaction_service._get_active_relations",
        _mock_relations(kind="iy"),
    )


def test_find_relations_hides_iy_with_ignored_frequency(iy_relation):
    """iy com item SN some do alerta e da contagem"""
    drug_list = _iy_drug_list(frequency_b=SN)
    config = _config(iy={"ignoreFrequencies": [SN, ACM]})

    shown = find_relations(drug_list, id_patient=1, is_cpoe=False)
    hidden = find_relations(drug_list, id_patient=1, is_cpoe=False, alert_config=config)

    assert shown["stats"]["iy"] == 1
    assert hidden["alerts"] == {}
    assert hidden["stats"]["iy"] == 0


def test_find_relations_iy_requires_interval_intersection(iy_relation):
    """iy sem horário em comum some; com horário em comum continua"""
    config = _config(iy={"requireIntervalIntersection": True})

    no_intersection = find_relations(
        _iy_drug_list(interval_a="08:00", interval_b="14:00"),
        id_patient=1,
        is_cpoe=False,
        alert_config=config,
    )
    intersection = find_relations(
        _iy_drug_list(interval_a="08:00 20:00", interval_b="20:00"),
        id_patient=1,
        is_cpoe=False,
        alert_config=config,
    )

    assert no_intersection["stats"]["iy"] == 0
    assert intersection["stats"]["iy"] == 1
    assert intersection["alerts"]["1"][0]["level"] == "medium"


# --- alert_service types ---------------------------------------------------


def _find_alerts(drugs, alert_config=None, dialysis="c", cultures=None):
    from services import alert_service

    return alert_service.find_alerts(
        drug_list=drugs,
        exams={"age": 50, "weight": 80},
        dialisys=dialysis,
        pregnant=None,
        lactating=None,
        schedules_fasting=None,
        cn_data=None,
        protocols=None,
        is_cpoe=False,
        cultures=cultures,
        alert_config=alert_config,
    )


def _kidney_and_max_dose_plus_drugs():
    """Two items raising kidney (dialysis) and maxDosePlus (10 + 10 > 15)"""
    return [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=61, dose=10, frequency=1, max_dose=15, kidney=True
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=62, dose=10, frequency=1, max_dose=15, kidney=True
        ),
    ]


def _types(result, id_prescription_drug: str) -> list[str]:
    return sorted(a["type"] for a in result["alerts"].get(id_prescription_drug, []))


@pytest.mark.parametrize(
    "alert_config",
    [None, AlertConfig(), AlertConfig.model_validate({"types": {"kidney": {}}})],
)
def test_alert_types_are_on_by_default(alert_config):
    """Sem config (ou sem desligar), todos os tipos de alerta continuam"""
    result = _find_alerts(_kidney_and_max_dose_plus_drugs(), alert_config)

    assert _types(result, "61") == ["kidney", "maxDosePlus"]
    assert result["stats"]["kidney"] == 2
    assert result["stats"]["maxDosePlus"] == 2


def test_an_alert_type_turned_off_is_neither_listed_nor_counted():
    """Tipo desligado some da lista e da contagem; os outros continuam"""
    config = AlertConfig.model_validate({"types": {"kidney": {"enabled": False}}})

    result = _find_alerts(_kidney_and_max_dose_plus_drugs(), config)

    assert _types(result, "61") == ["maxDosePlus"]
    assert _types(result, "62") == ["maxDosePlus"]
    assert result["stats"]["kidney"] == 0
    assert result["stats"]["maxDosePlus"] == 2


def test_every_alert_type_can_be_turned_off():
    """Todos os tipos desligados: nenhum alerta"""
    from models.enums import DrugAlertTypeEnum

    config = AlertConfig.model_validate(
        {"types": {t.value: {"enabled": False} for t in DrugAlertTypeEnum}}
    )

    result = _find_alerts(_kidney_and_max_dose_plus_drugs(), config)

    assert result["alerts"] == {}
    assert all(count == 0 for count in result["stats"].values())


def test_culture_class_alert_does_not_stand_in_for_a_type_turned_off():
    """Desligar cultureResistant não faz o alerta de classe aparecer no lugar"""
    from tests.unit.test_alerts import _culture

    drugs = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=61,
            dose=10,
            frequency=1,
            sctid="1111",
            drug_class="K1B1",
        )
    ]
    config = AlertConfig.model_validate(
        {"types": {"cultureResistant": {"enabled": False}}}
    )

    result = _find_alerts(
        drugs,
        config,
        dialysis=None,
        cultures=[_culture(drug="AMICACINA", sctid="1111", id_substance_class="K1B1")],
    )

    assert result["alerts"] == {}
    assert result["stats"]["cultureResistant"] == 0
    assert result["stats"]["cultureResistantClass"] == 0
