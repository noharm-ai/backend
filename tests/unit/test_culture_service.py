"""Unit tests for the culture summary grouping (services.culture_service).

The DynamoDB query is skipped in the TEST env, so the grouping is the only
part of the service a test can reach — and it is where the distinction
between a lab result and a model prediction is enforced.
"""

from decimal import Decimal

from services import culture_service


def _item(**overrides):
    """A DynamoDB noharm_cultura_resumo row, numbers as boto3 returns them."""
    item = {
        "ativo": True,
        "nomemedicamento": "OXACILINA",
        "microorganismo": "Microorganismo Teste",
        "nomematerial": "Sangue Total",
        "resultado": None,
        "predict": "S",
        "predict_proba": Decimal("0.7"),
        "datacoleta": "2024-03-01T12:17:03",
        "dataliberacao": "2024-03-08T07:17:02",
        "chave": "SANGUE TOTAL#MICROORGANISMO TESTE#OXACILINA",
    }
    item.update(overrides)
    return item


class TestGroupByDrug:
    """Tests for culture_service._group_by_drug."""

    def test_groups_rows_of_the_same_drug(self):
        """Two collections of one drug become one entry with two items."""
        result = culture_service._group_by_drug(
            [
                _item(chave="a", datacoleta="2024-03-01T12:17:03"),
                _item(chave="b", datacoleta="2024-03-05T12:17:03"),
            ]
        )

        assert len(result) == 1
        assert result[0]["drug"] == "OXACILINA"
        assert len(result[0]["items"]) == 2

    def test_items_are_ordered_by_collection_date_desc(self):
        """The most recent collection comes first, it is what the card shows."""
        result = culture_service._group_by_drug(
            [
                _item(chave="old", datacoleta="2024-03-01T12:17:03"),
                _item(chave="new", datacoleta="2024-03-05T12:17:03"),
            ]
        )

        assert [i["key"] for i in result[0]["items"]] == ["new", "old"]

    def test_drugs_are_sorted_alphabetically(self):
        """Drugs come out in alphabetical order."""
        result = culture_service._group_by_drug(
            [
                _item(nomemedicamento="VANCOMICINA"),
                _item(nomemedicamento="AMICACINA"),
            ]
        )

        assert [d["drug"] for d in result] == ["AMICACINA", "VANCOMICINA"]

    def test_decimal_probability_becomes_float(self):
        """boto3 Decimals would break json serialization."""
        result = culture_service._group_by_drug([_item()])

        assert result[0]["items"][0]["probability"] == 0.7
        assert isinstance(result[0]["items"][0]["probability"], float)

    def test_lab_result_suppresses_the_prediction(self):
        """A released result is never presented alongside a prediction."""
        result = culture_service._group_by_drug([_item(resultado="Resistente")])

        item = result[0]["items"][0]
        assert item["result"] == "Resistente"
        assert item["prediction"] is None
        assert item["probability"] is None

    def test_blank_result_is_treated_as_pending(self):
        """An empty result string means the culture is still pending."""
        result = culture_service._group_by_drug([_item(resultado="   ")])

        item = result[0]["items"][0]
        assert item["result"] is None
        assert item["prediction"] == "S"

    def test_low_confidence_prediction_is_dropped(self):
        """Below the threshold there is nothing to show, so no row at all."""
        assert (
            culture_service._group_by_drug([_item(predict_proba=Decimal("0.6"))]) == []
        )

    def test_pending_row_without_prediction_is_dropped(self):
        """No result and no prediction carries no information."""
        assert culture_service._group_by_drug([_item(predict=None)]) == []

    def test_inactive_rows_are_ignored(self):
        """Superseded rows are flagged inactive by the pipeline."""
        assert culture_service._group_by_drug([_item(ativo=False)]) == []

    def test_row_without_drug_is_ignored(self):
        """The grouping key is the drug, a row without one cannot be shown."""
        assert culture_service._group_by_drug([_item(nomemedicamento=None)]) == []

    def test_empty_input(self):
        """A patient with no cultures returns an empty list."""
        assert culture_service._group_by_drug([]) == []
