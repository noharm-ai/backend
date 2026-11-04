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


# --- kidney alert exams ----------------------------------------------------


def test_types_cover_every_alert_type():
    """Cada tipo de alerta (DrugAlertTypeEnum) tem sua entrada em types"""
    from models.alert_config import AlertTypesConfig
    from models.enums import DrugAlertTypeEnum

    assert set(AlertTypesConfig.model_fields) == {t.value for t in DrugAlertTypeEnum}


def test_unknown_alert_type_is_the_default():
    """Tipo desconhecido (ou atributo do modelo) não quebra: padrão"""
    config = AlertConfig()

    assert config.alert_type("other").enabled is True
    assert config.alert_type("model_config").enabled is True


def test_kidney_exams_defaults():
    """Padrão: os exames de hoje (ckd21/ckd adulto, swrtz2/swrtz1 pediátrico)"""
    kidney = AlertConfig().types.kidney

    assert kidney.adultExams == ["ckd21", "ckd"]
    assert kidney.pediatricExams == ["swrtz2", "swrtz1"]


def test_kidney_exams_are_normalized():
    """tpexam em minúsculas, sem repetição; lista vazia mantém o padrão"""
    kidney = AlertConfig.model_validate(
        {
            "types": {
                "kidney": {
                    "adultExams": [" TFG ", "tfg", "CKD21"],
                    "pediatricExams": [],
                }
            }
        }
    ).types.kidney

    assert kidney.adultExams == ["tfg", "ckd21"]
    assert kidney.pediatricExams == ["swrtz2", "swrtz1"]


def _kidney_alerts(exams: dict, alert_config=None, kidney_limit=30):
    from services import alert_service

    drugs = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=61, dose=10, frequency=1, kidney=kidney_limit
        )
    ]
    result = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys=None,
        pregnant=None,
        lactating=None,
        schedules_fasting=None,
        cn_data=None,
        protocols=None,
        is_cpoe=False,
        alert_config=alert_config,
    )
    return [a for a in result["alerts"].get("61", []) if a["type"] == "kidney"]


def _kidney_config(**kidney) -> AlertConfig:
    return AlertConfig.model_validate({"types": {"kidney": kidney}})


@pytest.mark.parametrize(
    "exams,alerted",
    [
        # ckd21 decides when it has a value, even if ckd is below the limit
        ({"ckd21": {"value": 50}, "ckd": {"value": 10}}, False),
        ({"ckd21": {"value": 10}, "ckd": {"value": 50}}, True),
        # ckd only without ckd21
        ({"ckd": {"value": 10}}, True),
        ({"ckd21": {"value": None}, "ckd": {"value": 10}}, True),
        ({}, False),
    ],
)
def test_kidney_adult_defaults_keep_todays_behaviour(exams, alerted):
    """Adulto, sem config: o primeiro exame com valor decide (ckd21, ckd)"""
    alerts = _kidney_alerts({"age": 50, "weight": 80, **exams})

    assert bool(alerts) is alerted


@pytest.mark.parametrize(
    "exams,alerted",
    [
        # any exam below the limit raises, in order
        ({"swrtz2": {"value": 50}, "swrtz1": {"value": 10}}, True),
        ({"swrtz2": {"value": 10}}, True),
        ({"swrtz1": {"value": 10}}, True),
        ({"swrtz2": {"value": 50}, "swrtz1": {"value": 50}}, False),
    ],
)
def test_kidney_pediatric_defaults_keep_todays_behaviour(exams, alerted):
    """Pediátrico, sem config: o primeiro exame abaixo do limite (swrtz2, swrtz1)"""
    alerts = _kidney_alerts({"age": 10, "weight": 30, **exams})

    assert bool(alerts) is alerted


def test_kidney_default_texts():
    """Os textos dos exames de hoje continuam (com espaçamento corrigido)"""
    adult = _kidney_alerts({"age": 50, "weight": 80, "ckd21": {"value": 10}})
    child = _kidney_alerts({"age": 10, "weight": 30, "swrtz1": {"value": 10}})

    assert adult[0]["text"].endswith(
        "função renal do paciente (10 mL/min) está abaixo de 30 mL/min."
    )
    assert child[0]["text"].endswith(
        "(10 mL/min/1.73m²) está abaixo de 30 mL/min. (Schwartz 1)"
    )


def test_kidney_adult_uses_the_configured_exam():
    """Adulto: usa o tpexam configurado; os padrões deixam de contar"""
    config = _kidney_config(adultExams=["tfg"])
    tfg = {"value": 20, "initials": "TFG", "unit": "mL/min/1.73m²"}

    alerts = _kidney_alerts(
        {"age": 50, "weight": 80, "ckd21": {"value": 50}, "tfg": tfg}, config
    )
    not_configured = _kidney_alerts(
        {"age": 50, "weight": 80, "ckd21": {"value": 10}}, config
    )

    assert len(alerts) == 1
    assert "(TFG: 20 mL/min/1.73m²) está abaixo de 30 mL/min." in alerts[0]["text"]
    assert not_configured == []


def test_kidney_adult_configured_order():
    """Adulto: na ordem configurada, o primeiro com valor decide"""
    config = _kidney_config(adultExams=["tfg", "ckd21"])

    with_tfg = _kidney_alerts(
        {"age": 50, "weight": 80, "tfg": {"value": 50}, "ckd21": {"value": 10}},
        config,
    )
    without_tfg = _kidney_alerts(
        {"age": 50, "weight": 80, "ckd21": {"value": 10}}, config
    )

    assert with_tfg == []
    assert len(without_tfg) == 1


def test_kidney_pediatric_uses_the_configured_exam():
    """Pediátrico: usa o tpexam configurado"""
    config = _kidney_config(pediatricExams=["tfgped"])

    alerts = _kidney_alerts(
        {
            "age": 10,
            "weight": 30,
            "swrtz2": {"value": 10},
            "tfgped": {"value": 20, "name": "TFG pediátrica", "unit": None},
        },
        config,
    )
    above = _kidney_alerts({"age": 10, "weight": 30, "tfgped": {"value": 50}}, config)

    assert len(alerts) == 1
    assert "(TFG pediátrica: 20) está abaixo de 30 mL/min." in alerts[0]["text"]
    assert above == []


@pytest.mark.parametrize("exam_type", ["age", "weight", "missing"])
def test_kidney_exam_that_is_not_an_exam_is_ignored(exam_type):
    """tpexam que não é exame (ou não existe) é ignorado, sem erro"""
    config = _kidney_config(adultExams=[exam_type, "ckd"])

    alerts = _kidney_alerts({"age": 50, "weight": 80, "ckd": {"value": 10}}, config)

    assert len(alerts) == 1


def test_kidney_non_numeric_value_is_ignored():
    """Valor não numérico não quebra a tela: o próximo exame vale"""
    config = _kidney_config(adultExams=["tfg", "ckd"])

    alerts = _kidney_alerts(
        {"age": 50, "weight": 80, "tfg": {"value": "n/a"}, "ckd": {"value": 10}},
        config,
    )

    assert len(alerts) == 1


def test_dialysis_alert_ignores_the_exams():
    """Em diálise o alerta não depende dos exames configurados"""
    from services import alert_service

    drugs = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=61, dose=10, frequency=1, kidney=30
        )
    ]
    result = alert_service.find_alerts(
        drug_list=drugs,
        exams={"age": 50, "weight": 80},
        dialisys="c",
        pregnant=None,
        lactating=None,
        schedules_fasting=None,
        cn_data=None,
        protocols=None,
        is_cpoe=False,
        alert_config=_kidney_config(adultExams=["tfg"]),
    )

    assert [a["type"] for a in result["alerts"]["61"]] == ["kidney"]


# --- IRA follows the kidney adult exams ---------------------------------------


def _ira_alerts(exams: dict, alert_config=None):
    """IRA alerts of a vancomycin item: daily dose 100, weight 80, so a renal
    function of 1 raises it (100 / 1 / 80 > 0,6219) and 300 does not"""
    from services import alert_service

    drugs = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=61, dose=10, frequency=10, drug_name="xxx vancoyyy"
        )
    ]
    result = alert_service.find_alerts(
        drug_list=drugs,
        exams={"weight": 80, **exams},
        dialisys=None,
        pregnant=None,
        lactating=None,
        schedules_fasting=None,
        cn_data=None,
        protocols=None,
        is_cpoe=False,
        alert_config=alert_config,
    )
    return [a for a in result["alerts"].get("61", []) if a["type"] == "ira"]


@pytest.mark.parametrize(
    "exams,alerted",
    [
        # ckd21 decides when it has a value
        ({"ckd21": {"value": 300}, "ckd": {"value": 1}}, False),
        ({"ckd21": {"value": 1}, "ckd": {"value": 300}}, True),
        # ckd only without ckd21
        ({"ckd": {"value": 1}}, True),
        ({}, False),
    ],
)
def test_ira_defaults_keep_todays_behaviour(exams, alerted):
    """IRA, sem config: a função renal é ckd21, ou ckd sem ckd21"""
    assert bool(_ira_alerts(exams)) is alerted


@pytest.mark.parametrize(
    "exams,alerted",
    [
        ({"tfg": {"value": 1}}, True),
        ({"tfg": {"value": 300}, "ckd": {"value": 1}}, False),
        # a default exam no longer counts when the schema chose others
        ({"ckd21": {"value": 1}}, False),
        # in order: the next exam when the first has no value
        ({"tfg": {"value": None}, "ckd": {"value": 1}}, True),
    ],
)
def test_ira_uses_the_configured_adult_exams(exams, alerted):
    """IRA usa os exames de adulto configurados no alerta renal (o primeiro com valor)"""
    config = _kidney_config(adultExams=["tfg", "ckd"])

    assert bool(_ira_alerts(exams, config)) is alerted


# --- interaction kind on/off --------------------------------------------------


def test_interaction_kinds_are_on_by_default():
    """Sem config, todos os tipos de interação continuam (nenhuma regra nova)"""
    for alert_config in (AlertConfig(), _config(dm={"enabled": True})):
        rules = _rules(
            "dm", _relation_item(), _relation_item(id="2"), alert_config=alert_config
        )
        assert "config_kind_disabled" not in rules


@pytest.mark.parametrize("kind", ["it", "dt", "dm", "iy", "sl", "rx"])
def test_a_disabled_interaction_kind_fails_its_rule(kind):
    """Tipo desligado: a regra falha e a mensagem (trace) nomeia o tipo"""
    from utils import examutils

    rules = evaluate_kind_rules(
        kind=kind,
        drug_from=_relation_item(rx=kind == "rx"),
        drug_to=_relation_item(id="2"),
        alert_config=_config(**{kind: {"enabled": False}}),
    )
    rule = next(r for r in rules if r["rule"] == "config_kind_disabled")

    assert rule["passed"] is False
    assert examutils.typeRelations[kind] in rule["message"]


def test_disabling_a_kind_does_not_touch_the_others():
    """Desligar dm não afeta iy"""
    rules = _rules(
        "iy",
        _relation_item(),
        _relation_item(id="2"),
        alert_config=_config(dm={"enabled": False}),
    )

    assert "config_kind_disabled" not in rules


def _relations_mock(kinds: list[str]):
    """Active relations of Drug A -> Drug B for the given kinds"""

    def mock(*args, **kwargs):
        return {
            f"211111-111111-{kind}": {
                "sctida": "211111",
                "sctidb": "111111",
                "kind": kind,
                "text": "Drug A interacts with Drug B",
                "level": "low",
            }
            for kind in kinds
        }

    return mock


def test_find_relations_hides_a_disabled_kind(monkeypatch):
    """dm desligado some do alerta e da contagem; iy continua"""
    monkeypatch.setattr(
        "services.alert_interaction_service._get_allergies", lambda **kw: []
    )
    monkeypatch.setattr(
        "services.alert_interaction_service._get_active_relations",
        _relations_mock(kinds=["dm", "iy"]),
    )
    config = _config(dm={"enabled": False}, iy={"enabled": True})

    shown = find_relations(_iy_drug_list(), id_patient=1, is_cpoe=False)
    configured = find_relations(
        _iy_drug_list(), id_patient=1, is_cpoe=False, alert_config=config
    )

    assert shown["stats"]["dm"] == 1
    assert shown["stats"]["iy"] == 1
    assert configured["stats"]["dm"] == 0
    assert configured["stats"]["iy"] == 1
    assert {a["type"] for alerts in configured["alerts"].values() for a in alerts} == {
        "iy"
    }
