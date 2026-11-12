"""Schema params in the noharm-store (pk schema_params): the schema's item over
the code defaults, section by section, and what a failure falls back to"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from models.alert_config import AlertConfig
from models.enums import FrequencyEnum
from models.schema_params import SchemaParams
from services import schema_params_service

SN = FrequencyEnum.SN.value
ACM = FrequencyEnum.ACM.value


def _store(items: dict, calls: list | None = None):
    """get_item_data stub returning the item's data (None when it has no item)"""

    def get_item_data(pk, sk):
        if calls is not None:
            calls.append((pk, sk))
        return items.get(sk)

    return get_item_data


def _load(monkeypatch, items: dict, schema="demo") -> SchemaParams:
    monkeypatch.setattr(
        "repository.store_repository.get_item_data", _store(items=items)
    )
    return schema_params_service._load(schema=schema)


def _alerts(**alerts) -> dict:
    """An item's data setting only the alerts section"""
    return {"alerts": alerts}


def test_no_item_is_the_defaults(monkeypatch):
    """Sem item: padrões do código (nenhum alerta escondido)"""
    config = _load(monkeypatch, items={})

    assert config == SchemaParams()
    assert config.alerts.alert_type("kidney").enabled is True
    assert config.alerts.interaction("iy").ignoreFrequencies == []
    assert config.alerts.interaction("iy").requireIntervalIntersection is False


def test_only_the_schema_item_is_read(monkeypatch):
    """Só o item do schema é lido (não há item global)"""
    calls = []
    monkeypatch.setattr(
        "repository.store_repository.get_item_data", _store(items={}, calls=calls)
    )

    schema_params_service._load(schema="demo")

    assert calls == [("schema_params", "demo")]


def test_without_schema_nothing_is_read(monkeypatch):
    """Sem schema (ex.: contexto sem usuário): padrões, sem leitura"""
    calls = []
    monkeypatch.setattr(
        "repository.store_repository.get_item_data", _store(items={}, calls=calls)
    )

    assert schema_params_service._load(schema=None) == SchemaParams()
    assert calls == []


def test_another_schema_item_does_not_apply(monkeypatch):
    """O item de outro schema não vale"""
    config = _load(
        monkeypatch,
        items={"other": _alerts(types={"kidney": {"enabled": False}})},
    )

    assert config.alerts.alert_type("kidney").enabled is True


def test_what_the_item_does_not_set_is_the_default(monkeypatch):
    """O que o item não define vem do código"""
    config = _load(
        monkeypatch,
        items={
            "demo": _alerts(
                types={"kidney": {"enabled": False}},
                interactions={"iy": {"ignoreFrequencies": [SN, ACM]}},
            )
        },
    )

    assert config.alerts.alert_type("kidney").enabled is False
    assert config.alerts.alert_type("liver").enabled is True
    assert config.alerts.interaction("iy").ignoreFrequencies == [SN, ACM]
    assert config.alerts.interaction("iy").requireIntervalIntersection is False
    assert config.alerts.interaction("dm").ignoreFrequencies == []


def test_dynamodb_numbers_are_decimal(monkeypatch):
    """O DynamoDB devolve números como Decimal"""
    config = _load(
        monkeypatch,
        items={
            "demo": _alerts(
                interactions={
                    "iy": {"ignoreFrequencies": [Decimal("33"), Decimal("0.5")]}
                }
            )
        },
    )

    assert config.alerts.interaction("iy").ignoreFrequencies == [33.0, 0.5]


def test_invalid_section_is_the_defaults(monkeypatch):
    """Seção inválida: padrões do código para ela"""
    config = _load(
        monkeypatch,
        items={"demo": _alerts(types={"kidney": {"enabled": "talvez"}})},
    )

    assert config == SchemaParams()


def test_invalid_section_does_not_drop_the_others(monkeypatch):
    """Uma seção inválida não derruba as outras seções do mesmo item"""
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


def test_data_that_is_not_a_map_is_the_defaults(monkeypatch):
    """data que não é mapa: padrões do código"""
    assert _load(monkeypatch, items={"demo": "x"}) == SchemaParams()


def test_unknown_keys_and_sections_are_ignored(monkeypatch):
    """Chave ou seção desconhecida não invalida o item"""
    config = _load(
        monkeypatch,
        items={
            "demo": {
                "future": {"x": 1},
                "alerts": {
                    "other": True,
                    "types": {"kidney": {"enabled": False, "y": 1}},
                    "interactions": {"iy": {"ignoreFrequencies": [SN], "y": 1}},
                },
            }
        },
    )

    assert config.alerts.alert_type("kidney").enabled is False
    assert config.alerts.interaction("iy").ignoreFrequencies == [SN]


def test_read_failure_is_the_defaults(monkeypatch):
    """Falha na leitura: padrões (nenhum alerta escondido)"""

    def fail(pk, sk):
        raise RuntimeError("timeout")

    monkeypatch.setattr("repository.store_repository.get_item_data", fail)

    assert schema_params_service._load(schema="demo") == SchemaParams()


def test_read_once_per_request(monkeypatch):
    """Lido uma vez por request (por schema)"""
    from mobile import app

    calls = []
    monkeypatch.setattr(
        "repository.store_repository.get_item_data", _store(items={}, calls=calls)
    )

    with app.test_request_context():
        schema_params_service.get_schema_params(schema="demo")
        schema_params_service.get_schema_params(schema="demo")

    assert calls == [("schema_params", "demo")]


def test_values_of_the_wrong_type_never_break_the_view(monkeypatch):
    """Nível que não é texto (lista, mapa): ignorado, sem erro (padrão do alerta)"""
    config = _load(
        monkeypatch,
        items={
            "demo": _alerts(
                types={"liver": {"level": ["high"]}, "elderly": {"level": {}}},
                interactions={"iy": {"ignoreLevels": [["low"], {}, "high"]}},
            )
        },
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
    monkeypatch.setattr(
        "repository.store_repository.get_item_data",
        _store(items={"demo": _alerts(types={"kidney": {"enabled": False}})}),
    )

    loaded = schema_params_service._load_with_status(schema="demo")

    assert loaded["status"] == "found"
    assert loaded["invalidSections"] == ["alerts"]
    assert loaded["params"] == SchemaParams()


def _with_cache(monkeypatch, clock: list):
    """Turns the container cache on (conftest turns it off) with a fake clock:
    clock[0] is the service's _now(), not the process-wide time.monotonic"""
    monkeypatch.setattr(schema_params_service, "CACHE_TTL_SECONDS", 60)
    monkeypatch.setattr(schema_params_service, "ERROR_RETRY_SECONDS", 10)
    monkeypatch.setattr(schema_params_service, "STALE_MAX_SECONDS", 300)
    monkeypatch.setattr(schema_params_service, "_now", lambda: clock[0])


def test_cached_in_the_container_until_it_expires(monkeypatch):
    """Cache por container: requests seguidas não leem a tabela de novo até o
    TTL vencer; depois disso a mudança feita no admin passa a valer"""
    clock = [1000.0]
    _with_cache(monkeypatch, clock)
    calls = []
    items = {"demo": _alerts(types={"kidney": {"enabled": False}})}
    monkeypatch.setattr(
        "repository.store_repository.get_item_data", _store(items=items, calls=calls)
    )

    first = schema_params_service.get_schema_params(schema="demo")
    items["demo"] = {}
    clock[0] += 59
    second = schema_params_service.get_schema_params(schema="demo")

    assert calls == [("schema_params", "demo")]
    assert first.alerts.alert_type("kidney").enabled is False
    assert second == first

    clock[0] += 1
    third = schema_params_service.get_schema_params(schema="demo")

    assert len(calls) == 2
    assert third == SchemaParams()


def test_cached_per_schema(monkeypatch):
    """Cada schema tem a sua entrada no cache"""
    clock = [1000.0]
    _with_cache(monkeypatch, clock)
    calls = []
    items = {"demo": _alerts(types={"kidney": {"enabled": False}})}
    monkeypatch.setattr(
        "repository.store_repository.get_item_data", _store(items=items, calls=calls)
    )

    demo = schema_params_service.get_schema_params(schema="demo")
    other = schema_params_service.get_schema_params(schema="other")
    schema_params_service.get_schema_params(schema="demo")

    assert calls == [("schema_params", "demo"), ("schema_params", "other")]
    assert demo.alerts.alert_type("kidney").enabled is False
    assert other == SchemaParams()


def test_no_item_is_cached_too(monkeypatch):
    """Schema sem item (padrões) também fica em cache: não lê a tabela a cada
    request"""
    clock = [1000.0]
    _with_cache(monkeypatch, clock)
    calls = []
    monkeypatch.setattr(
        "repository.store_repository.get_item_data", _store(items={}, calls=calls)
    )

    schema_params_service.get_schema_params(schema="demo")
    schema_params_service.get_schema_params(schema="demo")

    assert calls == [("schema_params", "demo")]


def test_a_failed_read_keeps_the_last_params_read(monkeypatch):
    """Falha ao reler depois do TTL: continuam valendo os últimos parâmetros
    lidos (não os padrões), e a tabela é lida de novo depois de
    ERROR_RETRY_SECONDS, não a cada request"""
    clock = [1000.0]
    _with_cache(monkeypatch, clock)
    calls = []
    state = {"fail": False}
    items = {"demo": _alerts(types={"kidney": {"enabled": False}})}

    def get_item_data(pk, sk):
        calls.append((pk, sk))
        if state["fail"]:
            raise RuntimeError("timeout")
        return items.get(sk)

    monkeypatch.setattr("repository.store_repository.get_item_data", get_item_data)

    schema_params_service.get_schema_params(schema="demo")
    state["fail"] = True
    clock[0] += 60
    stale = schema_params_service.get_schema_params(schema="demo")
    clock[0] += 9
    schema_params_service.get_schema_params(schema="demo")

    assert len(calls) == 2
    assert stale.alerts.alert_type("kidney").enabled is False

    state["fail"] = False
    items["demo"] = {}
    clock[0] += 1
    recovered = schema_params_service.get_schema_params(schema="demo")

    assert len(calls) == 3
    assert recovered == SchemaParams()


def test_a_failed_first_read_is_the_defaults_and_retried_soon(monkeypatch):
    """Falha sem nada em cache: padrões, e a tabela é lida de novo depois de
    ERROR_RETRY_SECONDS (não fica com os padrões pelo TTL inteiro)"""
    clock = [1000.0]
    _with_cache(monkeypatch, clock)
    calls = []
    state = {"fail": True}
    items = {"demo": _alerts(types={"kidney": {"enabled": False}})}

    def get_item_data(pk, sk):
        calls.append((pk, sk))
        if state["fail"]:
            raise RuntimeError("timeout")
        return items.get(sk)

    monkeypatch.setattr("repository.store_repository.get_item_data", get_item_data)

    assert schema_params_service.get_schema_params(schema="demo") == SchemaParams()
    clock[0] += 9
    schema_params_service.get_schema_params(schema="demo")
    assert len(calls) == 1

    state["fail"] = False
    clock[0] += 1
    config = schema_params_service.get_schema_params(schema="demo")

    assert len(calls) == 2
    assert config.alerts.alert_type("kidney").enabled is False


def test_stale_params_give_way_to_the_defaults(monkeypatch):
    """Falhas seguidas: os últimos parâmetros lidos valem só até
    STALE_MAX_SECONDS depois da leitura; depois, os padrões (que não escondem
    nenhum alerta), para uma mudança feita no admin não ficar presa pela queda"""
    clock = [1000.0]
    _with_cache(monkeypatch, clock)
    state = {"fail": False}
    items = {"demo": _alerts(types={"kidney": {"enabled": False}})}

    def get_item_data(pk, sk):
        if state["fail"]:
            raise RuntimeError("timeout")
        return items.get(sk)

    monkeypatch.setattr("repository.store_repository.get_item_data", get_item_data)

    schema_params_service.get_schema_params(schema="demo")
    state["fail"] = True

    clock[0] += 300
    stale = schema_params_service.get_schema_params(schema="demo")
    assert stale.alerts.alert_type("kidney").enabled is False

    clock[0] += 10
    expired = schema_params_service.get_schema_params(schema="demo")
    assert expired == SchemaParams()

    clock[0] += 10
    assert schema_params_service.get_schema_params(schema="demo") == SchemaParams()


def test_the_cached_params_cannot_be_changed_in_place(monkeypatch):
    """O mesmo objeto atende todas as requests do container: os modelos são
    congelados, uma request não muda os parâmetros das outras"""
    clock = [1000.0]
    _with_cache(monkeypatch, clock)
    config = schema_params_service.get_schema_params(schema="demo")

    with pytest.raises(ValidationError):
        config.alerts.types.kidney.enabled = False
    with pytest.raises(ValidationError):
        config.alerts = AlertConfig()

    assert schema_params_service.get_schema_params(schema="demo") == SchemaParams()
