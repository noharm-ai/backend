"""Reads from the noharm-store: one item by (pk, sk), its `data` as plain
values, no item told apart from an item without data"""

from decimal import Decimal

import pytest

from config import Config
from repository import store_repository

# the real function, taken at import: an autouse fixture (tests/conftest.py)
# replaces it so that no test calls AWS
_get_item_data = store_repository.get_item_data


class _FakeClient:
    """DynamoDB client stub: answers get_item with the item given"""

    def __init__(self, item=None, error=None):
        self.item = item
        self.error = error
        self.calls = []

    def get_item(self, **kwargs):
        """Records the call and answers like DynamoDB (no Item when not found)"""
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {} if self.item is None else {"Item": self.item}


def _client(monkeypatch, **kwargs) -> _FakeClient:
    client = _FakeClient(**kwargs)
    monkeypatch.setattr(store_repository, "_get_client", lambda: client)
    return client


def test_reads_the_item_by_its_key(monkeypatch):
    """Lê só o item (pk, sk) da tabela configurada, projetando o data"""
    client = _client(monkeypatch)

    _get_item_data(pk="schema_params", sk="demo")

    assert client.calls == [
        {
            "TableName": Config.NOHARM_STORE_TABLE,
            "Key": {"pk": {"S": "schema_params"}, "sk": {"S": "demo"}},
            "ProjectionExpression": "#data",
            "ExpressionAttributeNames": {"#data": "data"},
        }
    ]


def test_no_item_is_none(monkeypatch):
    """Sem item: None (diferente de item sem data)"""
    _client(monkeypatch, item=None)

    assert _get_item_data(pk="schema_params", sk="demo") is None


def test_item_without_data_is_empty(monkeypatch):
    """Item sem data: {}"""
    _client(monkeypatch, item={"pk": {"S": "schema_params"}})

    assert _get_item_data(pk="schema_params", sk="demo") == {}


def test_data_is_deserialized(monkeypatch):
    """O data volta como valores Python (números como Decimal)"""
    _client(
        monkeypatch,
        item={
            "data": {
                "M": {
                    "alerts": {
                        "M": {
                            "enabled": {"BOOL": False},
                            "ignoreFrequencies": {"L": [{"N": "33"}]},
                            "ignoreLevels": {"L": [{"S": "low"}]},
                        }
                    }
                }
            }
        },
    )

    assert _get_item_data(pk="schema_params", sk="demo") == {
        "alerts": {
            "enabled": False,
            "ignoreFrequencies": [Decimal("33")],
            "ignoreLevels": ["low"],
        }
    }


def test_a_dynamodb_failure_raises(monkeypatch):
    """Falha do DynamoDB sobe: quem chama decide (schema params: padrões)"""
    _client(monkeypatch, error=RuntimeError("timeout"))

    with pytest.raises(RuntimeError):
        _get_item_data(pk="schema_params", sk="demo")
