"""Schema params in the schema's memoria (tipo schema-params): the record over
the code defaults, section by section"""

from models.alert_config import AlertConfig
from models.enums import FrequencyEnum, MemoryEnum
from models.schema_params import SchemaParams
from services import schema_params_service

SN = FrequencyEnum.SN.value
ACM = FrequencyEnum.ACM.value
KIND = MemoryEnum.SCHEMA_PARAMS.value


def _load(value) -> SchemaParams:
    """The params in force for a record holding `value`"""
    return schema_params_service.from_memory(memory_itens={KIND: value}, schema="demo")


def _alerts(**alerts) -> dict:
    """A record's value setting only the alerts section"""
    return {"alerts": alerts}


def test_the_kind_is_an_admin_memory():
    """Only the admin project writes the record: no user can save it here"""
    from services import memory_service

    assert schema_params_service.KIND == "schema-params"
    assert memory_service.is_admin_memory(KIND)


def test_no_record_is_the_defaults():
    """Sem registro: padrões do código (nenhum alerta escondido)"""
    config = schema_params_service.from_memory(memory_itens={}, schema="demo")

    assert config == SchemaParams()
    assert config.alerts.alert_type("kidney").enabled is True
    assert config.alerts.interaction("iy").ignoreFrequencies == []
    assert config.alerts.interaction("iy").requireIntervalIntersection is False


def test_other_memory_records_do_not_apply():
    """Outros registros da memória lidos junto não valem como parâmetros"""
    config = schema_params_service.from_memory(
        memory_itens={"features": ["X"], "map-schedules-fasting": []}, schema="demo"
    )

    assert config == SchemaParams()


def test_what_the_record_does_not_set_is_the_default():
    """O que o registro não define vem do código"""
    config = _load(
        _alerts(
            types={"kidney": {"enabled": False}},
            interactions={"iy": {"ignoreFrequencies": [SN, ACM]}},
        )
    )

    assert config.alerts.alert_type("kidney").enabled is False
    assert config.alerts.alert_type("liver").enabled is True
    assert config.alerts.interaction("iy").ignoreFrequencies == [SN, ACM]
    assert config.alerts.interaction("iy").requireIntervalIntersection is False
    assert config.alerts.interaction("dm").ignoreFrequencies == []


def test_json_numbers_are_read_as_given():
    """O JSON traz inteiros e decimais como números do Python"""
    config = _load(_alerts(interactions={"iy": {"ignoreFrequencies": [33, 0.5]}}))

    assert config.alerts.interaction("iy").ignoreFrequencies == [33.0, 0.5]


def test_invalid_section_is_the_defaults():
    """Seção inválida: padrões do código para ela"""
    config = _load(_alerts(types={"kidney": {"enabled": "talvez"}}))

    assert config == SchemaParams()


def test_invalid_section_does_not_drop_the_others(monkeypatch):
    """Uma seção inválida não derruba as outras seções do mesmo registro"""
    # a second section, as a future one would be declared
    monkeypatch.setattr(
        schema_params_service,
        "_SECTIONS",
        {**schema_params_service._SECTIONS, "other": AlertConfig},
    )

    sections = schema_params_service._validated_sections(
        data={
            **_alerts(types={"kidney": {"enabled": False}}),
            "other": {"types": "x"},
        },
        schema="demo",
    )

    assert set(sections) == {"alerts"}
    assert sections["alerts"].alert_type("kidney").enabled is False


def test_a_value_that_is_not_a_map_is_the_defaults():
    """valor que não é mapa: padrões do código"""
    assert _load("x") == SchemaParams()
    assert _load([1, 2]) == SchemaParams()


def test_unknown_keys_and_sections_are_ignored():
    """Chave ou seção desconhecida não invalida o registro"""
    config = _load(
        {
            "future": {"x": 1},
            "alerts": {
                "other": True,
                "types": {"kidney": {"enabled": False, "y": 1}},
                "interactions": {"iy": {"ignoreFrequencies": [SN], "y": 1}},
            },
        }
    )

    assert config.alerts.alert_type("kidney").enabled is False
    assert config.alerts.interaction("iy").ignoreFrequencies == [SN]


def test_values_of_the_wrong_type_never_break_the_view():
    """Nível que não é texto (lista, mapa): ignorado, sem erro (padrão do alerta)"""
    config = _load(
        _alerts(
            types={"liver": {"level": ["high"]}, "elderly": {"level": {}}},
            interactions={"iy": {"ignoreLevels": [["low"], {}, "high"]}},
        )
    )

    assert config.alerts.alert_type("liver").level is None
    assert config.alerts.alert_type("elderly").level is None
    assert config.alerts.interaction("iy").ignoreLevels == ["high"]


def test_an_unexpected_error_in_a_section_is_the_defaults(monkeypatch):
    """Erro inesperado (não de validação) ao ler uma seção: a seção cai nos
    padrões e é apontada como inválida, sem derrubar a tela"""

    class Broken:
        """Section model that fails with an error pydantic does not wrap"""

        @staticmethod
        def model_validate(data):
            raise TypeError("unhashable type: 'list'")

    monkeypatch.setitem(schema_params_service._SECTIONS, "alerts", Broken)

    loaded = schema_params_service._load_with_status(
        value=_alerts(types={"kidney": {"enabled": False}}),
        found=True,
        schema="demo",
    )

    assert loaded["status"] == "found"
    assert loaded["invalidSections"] == ["alerts"]
    assert loaded["params"] == SchemaParams()
