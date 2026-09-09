"""Unit tests for the culture summary grouping (services.culture_service).

The DynamoDB query is skipped in the TEST env, so the grouping is the only
part of the service a test can reach — and it is where the distinction
between a lab result and a model prediction is enforced.
"""

from decimal import Decimal

import pytest

from models.enums import CultureResultTypeEnum
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
        "fkitemexame": Decimal("172435010004"),
        "datacoleta": "2024-03-01T12:17:03",
        "dataliberacao": "2024-03-08T07:17:02",
        "chave": "SANGUE TOTAL#MICROORGANISMO TESTE#OXACILINA",
        "sctid": Decimal("1111"),
        "idclasse": "K1B1",
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

    def test_released_result_comes_before_a_pending_collection(self):
        """A drug with an antibiogram is never represented by a prediction.

        The card reads the first item of the drug, so a newer collection that
        is still pending must not push the released result out of it.
        """
        result = culture_service._group_by_drug(
            [
                _item(
                    chave="pending",
                    datacoleta="2024-03-10T12:17:03",
                    resultado=None,
                ),
                _item(
                    chave="released",
                    datacoleta="2024-03-01T12:17:03",
                    resultado="Resistente",
                ),
            ]
        )

        items = result[0]["items"]
        assert [i["key"] for i in items] == ["released", "pending"]
        assert items[0]["resultType"] == "R"

    def test_collection_date_still_orders_items_of_the_same_kind(self):
        """Results are ordered among themselves, and so are the pending ones."""
        result = culture_service._group_by_drug(
            [
                _item(
                    chave="old-result",
                    datacoleta="2024-03-01T12:17:03",
                    resultado="Sensível",
                ),
                _item(
                    chave="new-pending",
                    datacoleta="2024-03-12T12:17:03",
                    resultado=None,
                ),
                _item(
                    chave="new-result",
                    datacoleta="2024-03-05T12:17:03",
                    resultado="Resistente",
                ),
                _item(
                    chave="old-pending",
                    datacoleta="2024-03-02T12:17:03",
                    resultado=None,
                ),
            ]
        )

        assert [i["key"] for i in result[0]["items"]] == [
            "new-result",
            "old-result",
            "new-pending",
            "old-pending",
        ]

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

    def test_decimal_exam_item_becomes_int(self):
        """The culture identifier is a Decimal too, and is what the card counts."""
        result = culture_service._group_by_drug([_item()])

        assert result[0]["items"][0]["idExamItem"] == 172435010004
        assert isinstance(result[0]["items"][0]["idExamItem"], int)

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


class TestClassifyResult:
    """Tests for culture_service.classify_result.

    The wordings below are the ones the hospitals send today; adding a new one
    to RESULT_TYPES must not require touching the screen that shows it.
    """

    @pytest.mark.parametrize(
        "result",
        [
            "S",
            "Sensível",
            "Sensível,aumentando exposição",
            "Sensível Dose-Dependente",
            "intermediário",
        ],
    )
    def test_susceptible_wordings(self, result):
        """Every wording that means susceptible is classified as such."""
        assert (
            culture_service.classify_result(result) == CultureResultTypeEnum.SUSCEPTIBLE
        )

    @pytest.mark.parametrize(
        "result",
        [
            "R",
            "RESISTENTE",
            "resistente",
            "Resistente",
        ],
    )
    def test_resistant_wordings(self, result):
        """Every wording that means resistant is classified as such."""
        assert (
            culture_service.classify_result(result) == CultureResultTypeEnum.RESISTANT
        )

    @pytest.mark.parametrize(
        "result, expected",
        [
            ("  resistente  ", CultureResultTypeEnum.RESISTANT),
            ("SENSIVEL", CultureResultTypeEnum.SUSCEPTIBLE),
            ("Sensível  Dose-Dependente", CultureResultTypeEnum.SUSCEPTIBLE),
        ],
    )
    def test_accent_case_and_spacing_are_ignored(self, result, expected):
        """The same wording written differently reaches the same type."""
        assert culture_service.classify_result(result) == expected

    @pytest.mark.parametrize(
        "result, expected",
        [
            ("Resistente Induzível", CultureResultTypeEnum.RESISTANT),
            ("Sensivel - vide observação", CultureResultTypeEnum.SUSCEPTIBLE),
            ("Suscetível", CultureResultTypeEnum.SUSCEPTIBLE),
        ],
    )
    def test_unenumerated_variants_fall_back_to_the_prefix(self, result, expected):
        """A wording nobody listed is still readable when it starts the same."""
        assert culture_service.classify_result(result) == expected

    @pytest.mark.parametrize("result", [None, "Não realizado", "*"])
    def test_unreadable_result_is_unknown(self, result):
        """A result that means neither one nor the other is not guessed."""
        assert culture_service.classify_result(result) == CultureResultTypeEnum.UNKNOWN


class TestResultDetail:
    """Tests for culture_service.result_detail."""

    @pytest.mark.parametrize("result", ["S", "Sensível", "R", "RESISTENTE"])
    def test_plain_wording_has_no_detail(self, result):
        """The group header already says it, the card does not repeat it."""
        result_type = culture_service.classify_result(result)

        assert culture_service.result_detail(result, result_type) is None

    @pytest.mark.parametrize(
        "result",
        ["intermediário", "Sensível Dose-Dependente", "Não realizado"],
    )
    def test_meaningful_wording_is_kept(self, result):
        """A wording the type does not convey stays visible on the card."""
        result_type = culture_service.classify_result(result)

        assert culture_service.result_detail(result, result_type) == result


class TestGroupedResultType:
    """The classification reaches the payload the prescription carries."""

    def test_result_is_classified(self):
        """The card groups by resultType, never by the free text."""
        result = culture_service._group_by_drug([_item(resultado="RESISTENTE")])

        item = result[0]["items"][0]
        assert item["resultType"] == "R"
        assert item["resultDetail"] is None

    def test_intermediate_result_is_susceptible_and_keeps_its_wording(self):
        """ "intermediário" is susceptible, but the card still spells it out."""
        result = culture_service._group_by_drug([_item(resultado="intermediário")])

        item = result[0]["items"][0]
        assert item["resultType"] == "S"
        assert item["resultDetail"] == "intermediário"

    def test_pending_culture_has_no_result_type(self):
        """A pending culture is described by its prediction alone."""
        result = culture_service._group_by_drug([_item()])

        item = result[0]["items"][0]
        assert item["resultType"] is None
        assert item["resultDetail"] is None
        assert item["predictionType"] == "S"

    def test_prediction_shares_the_result_alphabet(self):
        """The card groups predictions with the same rule it groups results."""
        result = culture_service._group_by_drug([_item(predict="R")])

        assert result[0]["items"][0]["predictionType"] == "R"


class TestSubstanceLink:
    """The substance is what lets a culture be compared to a prescribed item."""

    def test_sctid_is_passed_through_as_int(self):
        """A Decimal sctid would break json serialization."""
        result = culture_service._group_by_drug([_item()])

        assert result[0]["sctid"] == 1111
        assert isinstance(result[0]["sctid"], int)

    def test_string_sctid_is_converted(self):
        """DynamoDB may store the id as a string, and it has to key an int."""
        result = culture_service._group_by_drug([_item(sctid="1111")])

        assert result[0]["sctid"] == 1111

    @pytest.mark.parametrize("sctid", [None, "", "not-a-number"])
    def test_unusable_sctid_becomes_none(self, sctid):
        """A drug the pipeline could not map stays on the card, without alerts."""
        result = culture_service._group_by_drug([_item(sctid=sctid)])

        assert result[0]["sctid"] is None

    def test_substance_class_is_passed_through(self):
        """The class is what raises the "same class" alert."""
        result = culture_service._group_by_drug([_item()])

        assert result[0]["idSubstanceClass"] == "K1B1"

    def test_missing_substance_class_becomes_none(self):
        """A drug without a class only raises the alert of its own substance."""
        result = culture_service._group_by_drug([_item(idclasse=None)])

        assert result[0]["idSubstanceClass"] is None

    def test_mapping_is_taken_from_the_row_that_has_one(self):
        """Only some collections of a drug may carry the mapping."""
        result = culture_service._group_by_drug(
            [
                _item(chave="a", sctid=None, idclasse=None),
                _item(chave="b"),
            ]
        )

        assert len(result) == 1
        assert result[0]["sctid"] == 1111
        assert result[0]["idSubstanceClass"] == "K1B1"
