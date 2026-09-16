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

    def test_resistant_result_is_read_ahead_of_a_newer_susceptible_one(self):
        """The reading of a drug is its worst released result, not its latest.

        Susceptible for the Klebsiella of a newer blood culture and resistant
        for the Pseudomonas of an older tracheal aspirate: the drug does not
        cover the patient, so the card must not group it as susceptible just
        because the susceptible result came last.
        """
        result = culture_service._group_by_drug(
            [
                _item(
                    chave="susceptible",
                    microorganismo="Klebsiella Teste",
                    nomematerial="Hemocultura",
                    datacoleta="2024-03-11T23:53:00",
                    resultado="Sensível",
                ),
                _item(
                    chave="resistant",
                    microorganismo="Pseudomonas Teste",
                    nomematerial="Aspirado Traqueal",
                    datacoleta="2024-03-07T11:24:00",
                    resultado="Resistente",
                ),
            ]
        )

        items = result[0]["items"]
        assert [i["key"] for i in items] == ["resistant", "susceptible"]
        assert items[0]["resultType"] == "R"

    def test_unreadable_result_outranks_a_susceptible_one_but_not_a_resistance(
        self,
    ):
        """A wording the classifier could not read must not be hidden under a
        susceptible result, and must not be stated as a resistance either: the
        card shows it, spelled out."""
        result = culture_service._group_by_drug(
            [
                _item(
                    chave="susceptible",
                    datacoleta="2024-03-09T12:17:03",
                    resultado="Sensível",
                ),
                _item(
                    chave="unknown",
                    datacoleta="2024-03-05T12:17:03",
                    resultado="Ver observação",
                ),
            ]
        )

        assert [i["key"] for i in result[0]["items"]] == ["unknown", "susceptible"]

        result = culture_service._group_by_drug(
            [
                _item(
                    chave="unknown",
                    datacoleta="2024-03-09T12:17:03",
                    resultado="Ver observação",
                ),
                _item(
                    chave="resistant",
                    datacoleta="2024-03-05T12:17:03",
                    resultado="Resistente",
                ),
            ]
        )

        assert [i["key"] for i in result[0]["items"]] == ["resistant", "unknown"]

    def test_collection_date_orders_results_of_the_same_kind(self):
        """Worst first, and inside each kind the most recent collection first:
        the order the modal reads. Pending collections stay last."""
        result = culture_service._group_by_drug(
            [
                _item(
                    chave="old-resistant",
                    datacoleta="2024-03-01T12:17:03",
                    resultado="Resistente",
                ),
                _item(
                    chave="new-susceptible",
                    datacoleta="2024-03-09T12:17:03",
                    resultado="Sensível",
                ),
                _item(
                    chave="old-susceptible",
                    datacoleta="2024-03-03T12:17:03",
                    resultado="Sensível",
                ),
                _item(
                    chave="new-resistant",
                    datacoleta="2024-03-07T12:17:03",
                    resultado="Resistente",
                ),
                _item(
                    chave="pending",
                    datacoleta="2024-03-12T12:17:03",
                    resultado=None,
                ),
            ]
        )

        assert [i["key"] for i in result[0]["items"]] == [
            "new-resistant",
            "old-resistant",
            "new-susceptible",
            "old-susceptible",
            "pending",
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


def _drug(prescribed=True, result="Resistente", result_type="R", items=None):
    """A drug of the flagged summary (alert_service.flag_prescribed_cultures)"""

    if items is None:
        items = [
            {
                "key": "SANGUE TOTAL#MICROORGANISMO TESTE#OXACILINA",
                "idExamItem": 172435010004,
                "result": result,
                "resultType": result_type,
                "prediction": None,
                "predictionType": None,
            }
        ]

    return {
        "drug": "OXACILINA",
        "sctid": 1111,
        "idSubstanceClass": "K1B1",
        "prescribed": prescribed,
        "items": items,
    }


class TestCultureStats:
    """Tests for culture_service.get_culture_stats: the summary the prescription
    view carries instead of the cultures themselves."""

    def test_counts_resistant_drugs_in_use(self):
        cultures = [
            _drug(prescribed=True),
            _drug(prescribed=True),
            _drug(prescribed=False),
        ]

        assert culture_service.get_culture_stats(cultures) == {"resistantInUse": 2}

    def test_susceptible_drug_in_use_does_not_count(self):
        cultures = [_drug(prescribed=True, result="Sensível", result_type="S")]

        assert culture_service.get_culture_stats(cultures) == {"resistantInUse": 0}

    def test_predicted_resistance_does_not_count(self):
        """The collection is pending: a prediction must not be stated as the
        lab result, so it never flags the tab."""
        items = [
            {
                "key": "a",
                "result": None,
                "resultType": None,
                "prediction": "R",
                "predictionType": "R",
            }
        ]

        assert culture_service.get_culture_stats([_drug(items=items)]) == {
            "resistantInUse": 0
        }

    def test_drug_is_read_by_its_first_item(self):
        """A released resistance comes first, ahead of a pending prediction of
        a newer collection (_group_by_drug)."""
        items = [
            {"key": "a", "result": "Resistente", "resultType": "R"},
            {"key": "b", "result": None, "resultType": None, "prediction": "S"},
        ]

        assert culture_service.get_culture_stats([_drug(items=items)]) == {
            "resistantInUse": 1
        }

    @pytest.mark.parametrize("cultures", [None, []])
    def test_no_cultures(self, cultures):
        assert culture_service.get_culture_stats(cultures) == {"resistantInUse": 0}


class TestToCard:
    """Tests for culture_service.to_card: the shape served to the culture card."""

    def test_hides_the_substance_class_and_exam_item(self):
        card = culture_service.to_card([_drug()])

        assert len(card) == 1
        assert "idSubstanceClass" not in card[0]
        assert "idExamItem" not in card[0]["items"][0]

    def test_keeps_the_substance_id(self):
        """The card asks the alternatives of a prescribed drug by it"""
        card = culture_service.to_card([_drug()])

        assert card[0]["sctid"] == 1111

    def test_keeps_what_the_card_reads(self):
        card = culture_service.to_card([_drug()])

        assert card[0]["drug"] == "OXACILINA"
        assert card[0]["prescribed"] is True
        assert card[0]["items"][0]["result"] == "Resistente"
        assert card[0]["items"][0]["resultType"] == "R"

    def test_does_not_mutate_the_summary(self):
        """The alerts still read the mapping from the same list"""
        cultures = [_drug()]

        culture_service.to_card(cultures)

        assert cultures[0]["sctid"] == 1111
        assert cultures[0]["items"][0]["idExamItem"] == 172435010004

    @pytest.mark.parametrize("cultures", [None, []])
    def test_no_cultures(self, cultures):
        assert culture_service.to_card(cultures) == []


# --- alternatives -----------------------------------------------------------

SPECIMEN = 900001
OTHER_SPECIMEN = 900002

# the AWaRe level of every substance below (repository/substance_repository)
LEVELS = {
    1111: {"name": "OXACILINA", "atbLevel": 1},
    2222: {"name": "AMICACINA", "atbLevel": 1},
    3333: {"name": "CEFEPIME", "atbLevel": 2},
    4444: {"name": "MEROPENEM", "atbLevel": 3},
    5555: {"name": "LINEZOLIDA", "atbLevel": None},
}


def _tested(
    drug: str,
    sctid,
    result="Sensível",
    result_type="S",
    specimen=SPECIMEN,
    collection_date="2024-03-01T12:17:03",
    prescribed=False,
    items=None,
):
    """A drug of the summary, tested in one specimen"""

    if items is None:
        items = [
            _tested_item(
                result=result,
                result_type=result_type,
                specimen=specimen,
                collection_date=collection_date,
            )
        ]

    return {
        "drug": drug,
        "sctid": sctid,
        "idSubstanceClass": None,
        "prescribed": prescribed,
        "items": items,
    }


def _tested_item(
    result="Sensível",
    result_type="S",
    specimen=SPECIMEN,
    collection_date="2024-03-01T12:17:03",
    prediction=None,
):
    return {
        "key": f"{specimen}#{result}",
        "idExamItem": specimen,
        "microorganism": "Microorganismo Teste",
        "material": "Sangue Total",
        "result": result,
        "resultType": result_type if result is not None else None,
        "resultDetail": None,
        "prediction": prediction,
        "predictionType": prediction,
        "collectionDate": collection_date,
        "releaseDate": "2024-03-08T07:17:02",
    }


def _names(alternatives):
    return [a["drug"] for a in alternatives]


class TestBuildAlternatives:
    """Tests for culture_service.build_alternatives: what the antibiogram
    suggests in place of a prescribed antimicrobial, on the AWaRe scale."""

    def test_resistant_drug_lists_every_susceptible_option_in_aware_order(self):
        """Escalation: the prescribed drug tested resistant, so every drug
        that tested susceptible in the same specimen applies, the least
        aggressive first and the unclassified ones last."""
        cultures = [
            _tested("CEFEPIME", 3333, result="Resistente", result_type="R"),
            _tested("MEROPENEM", 4444),
            _tested("AMICACINA", 2222),
            _tested("LINEZOLIDA", 5555),
        ]

        result = culture_service.build_alternatives(cultures, 3333, LEVELS)

        assert result["sctid"] == 3333
        assert result["drug"] == "CEFEPIME"
        assert result["substance"] == {"name": "CEFEPIME", "atbLevel": 2}
        assert len(result["cultures"]) == 1

        culture = result["cultures"][0]
        assert culture["mode"] == "escalation"
        assert culture["resultType"] == "R"
        assert culture["microorganism"] == "Microorganismo Teste"
        assert _names(culture["alternatives"]) == [
            "AMICACINA",
            "MEROPENEM",
            "LINEZOLIDA",
        ]
        assert [a["atbLevel"] for a in culture["alternatives"]] == [1, 3, None]

    def test_susceptible_drug_lists_only_less_aggressive_options(self):
        """De-escalation: the prescribed drug works, so only a susceptible
        drug lower on the AWaRe scale is worth a change."""
        cultures = [
            _tested("MEROPENEM", 4444),
            _tested("CEFEPIME", 3333),
            _tested("AMICACINA", 2222),
            _tested("LINEZOLIDA", 5555),
        ]

        result = culture_service.build_alternatives(cultures, 4444, LEVELS)

        culture = result["cultures"][0]
        assert culture["mode"] == "deescalation"
        assert _names(culture["alternatives"]) == ["AMICACINA", "CEFEPIME"]

    def test_susceptible_drug_at_the_lowest_level_has_nothing_to_step_down_to(self):
        cultures = [_tested("AMICACINA", 2222), _tested("CEFEPIME", 3333)]

        result = culture_service.build_alternatives(cultures, 2222, LEVELS)

        assert result["cultures"][0]["mode"] == "deescalation"
        assert result["cultures"][0]["alternatives"] == []

    def test_susceptible_drug_without_a_level_suggests_nothing(self):
        """Without a level on the prescribed side nothing is "less aggressive"."""
        cultures = [_tested("LINEZOLIDA", 5555), _tested("AMICACINA", 2222)]

        result = culture_service.build_alternatives(cultures, 5555, LEVELS)

        assert result["substance"]["atbLevel"] is None
        assert result["cultures"][0]["alternatives"] == []

    def test_resistant_options_are_never_suggested(self):
        cultures = [
            _tested("CEFEPIME", 3333, result="Resistente", result_type="R"),
            _tested("MEROPENEM", 4444, result="Resistente", result_type="R"),
            _tested("AMICACINA", 2222),
        ]

        result = culture_service.build_alternatives(cultures, 3333, LEVELS)

        assert _names(result["cultures"][0]["alternatives"]) == ["AMICACINA"]

    def test_only_the_same_specimen_counts(self):
        """A drug that tested susceptible against another culture says nothing
        about the microorganism the prescribed drug failed against."""
        cultures = [
            _tested("CEFEPIME", 3333, result="Resistente", result_type="R"),
            _tested("AMICACINA", 2222, specimen=OTHER_SPECIMEN),
            _tested("MEROPENEM", 4444),
        ]

        result = culture_service.build_alternatives(cultures, 3333, LEVELS)

        assert _names(result["cultures"][0]["alternatives"]) == ["MEROPENEM"]

    def test_specimen_without_exam_item_is_matched_by_collection(self):
        cultures = [
            _tested(
                "CEFEPIME", 3333, result="Resistente", result_type="R", specimen=None
            ),
            _tested("AMICACINA", 2222, specimen=None),
            _tested(
                "MEROPENEM", 4444, specimen=None, collection_date="2024-02-01T10:00:00"
            ),
        ]

        result = culture_service.build_alternatives(cultures, 3333, LEVELS)

        assert _names(result["cultures"][0]["alternatives"]) == ["AMICACINA"]

    def test_prediction_never_suggests_anything(self):
        """A pending collection is represented by a prediction, and a
        prediction is not the lab result: neither as the prescribed side nor
        as an option."""
        cultures = [
            _tested(
                "CEFEPIME",
                3333,
                items=[_tested_item(result=None, prediction="R")],
            ),
            _tested(
                "AMICACINA", 2222, items=[_tested_item(result=None, prediction="S")]
            ),
        ]

        result = culture_service.build_alternatives(cultures, 3333, LEVELS)

        assert result["drug"] == "CEFEPIME"
        assert result["cultures"] == []

    def test_unclassified_result_is_skipped(self):
        cultures = [
            _tested("CEFEPIME", 3333, result="Indeterminado", result_type="U"),
            _tested("AMICACINA", 2222),
        ]

        result = culture_service.build_alternatives(cultures, 3333, LEVELS)

        assert result["cultures"] == []

    def test_one_block_per_specimen_most_recent_first(self):
        cultures = [
            _tested(
                "CEFEPIME",
                3333,
                items=[
                    _tested_item(
                        result="Resistente",
                        result_type="R",
                        specimen=SPECIMEN,
                        collection_date="2024-03-01T12:17:03",
                    ),
                    _tested_item(
                        result="Sensível",
                        result_type="S",
                        specimen=OTHER_SPECIMEN,
                        collection_date="2024-03-10T12:17:03",
                    ),
                ],
            ),
            _tested("AMICACINA", 2222, specimen=SPECIMEN),
            _tested("MEROPENEM", 4444, specimen=OTHER_SPECIMEN),
        ]

        result = culture_service.build_alternatives(cultures, 3333, LEVELS)

        assert [c["idExamItem"] for c in result["cultures"]] == [
            OTHER_SPECIMEN,
            SPECIMEN,
        ]
        assert result["cultures"][0]["mode"] == "deescalation"
        # MEROPENEM is more aggressive than CEFEPIME: no step down there
        assert result["cultures"][0]["alternatives"] == []
        assert result["cultures"][1]["mode"] == "escalation"
        assert _names(result["cultures"][1]["alternatives"]) == ["AMICACINA"]

    def test_the_substance_itself_is_not_an_option(self):
        """The lab may list the substance under two names, both susceptible"""
        cultures = [
            _tested("CEFEPIME", 3333, result="Resistente", result_type="R"),
            _tested("CEFEPIME 1G", 3333),
            _tested("AMICACINA", 2222),
        ]

        result = culture_service.build_alternatives(cultures, 3333, LEVELS)

        assert _names(result["cultures"][0]["alternatives"]) == ["AMICACINA"]

    def test_string_sctid_is_accepted(self):
        cultures = [
            _tested("CEFEPIME", "3333", result="Resistente", result_type="R"),
            _tested("AMICACINA", "2222"),
        ]

        result = culture_service.build_alternatives(cultures, "3333", LEVELS)

        assert result["sctid"] == 3333
        assert _names(result["cultures"][0]["alternatives"]) == ["AMICACINA"]
        assert result["cultures"][0]["alternatives"][0]["sctid"] == 2222

    def test_substance_the_lab_did_not_test(self):
        result = culture_service.build_alternatives(
            [_tested("AMICACINA", 2222)], 4444, LEVELS
        )

        assert result == {
            "sctid": 4444,
            "substance": {"name": "MEROPENEM", "atbLevel": 3},
            "drug": None,
            "cultures": [],
        }

    @pytest.mark.parametrize("sctid", [None, "", "abc"])
    def test_unusable_sctid(self, sctid):
        result = culture_service.build_alternatives(
            [_tested("AMICACINA", 2222)], sctid, LEVELS
        )

        assert result["sctid"] is None
        assert result["cultures"] == []

    @pytest.mark.parametrize("cultures", [None, []])
    def test_no_cultures(self, cultures):
        result = culture_service.build_alternatives(cultures, 3333, LEVELS)

        assert result["cultures"] == []


class TestFlagAlternatives:
    """Tests for culture_service.flag_alternatives: whether the card offers the
    alternatives of a prescribed drug."""

    def test_flags_the_prescribed_drugs_only(self):
        cultures = [
            _tested(
                "CEFEPIME", 3333, result="Resistente", result_type="R", prescribed=True
            ),
            _tested("AMICACINA", 2222),
        ]

        culture_service.flag_alternatives(cultures, LEVELS)

        assert cultures[0]["hasAlternatives"] is True
        assert "hasAlternatives" not in cultures[1]

    def test_susceptible_drug_without_a_step_down_is_not_flagged(self):
        cultures = [
            _tested("AMICACINA", 2222, prescribed=True),
            _tested("MEROPENEM", 4444),
        ]

        culture_service.flag_alternatives(cultures, LEVELS)

        assert cultures[0]["hasAlternatives"] is False

    def test_susceptible_drug_with_a_step_down_is_flagged(self):
        cultures = [
            _tested("MEROPENEM", 4444, prescribed=True),
            _tested("AMICACINA", 2222),
        ]

        culture_service.flag_alternatives(cultures, LEVELS)

        assert cultures[0]["hasAlternatives"] is True

    def test_resistant_drug_with_nothing_susceptible_is_not_flagged(self):
        cultures = [
            _tested(
                "CEFEPIME", 3333, result="Resistente", result_type="R", prescribed=True
            ),
            _tested("MEROPENEM", 4444, result="Resistente", result_type="R"),
        ]

        culture_service.flag_alternatives(cultures, LEVELS)

        assert cultures[0]["hasAlternatives"] is False

    def test_flag_reaches_the_card(self):
        cultures = [
            _tested("MEROPENEM", 4444, prescribed=True),
            _tested("AMICACINA", 2222),
        ]

        card = culture_service.to_card(
            culture_service.flag_alternatives(cultures, LEVELS)
        )

        assert card[0]["hasAlternatives"] is True

    @pytest.mark.parametrize("cultures", [None, []])
    def test_no_cultures(self, cultures):
        assert culture_service.flag_alternatives(cultures, LEVELS) == cultures


class TestCultureSctids:
    def test_lists_the_mapped_substances(self):
        cultures = [
            _tested("AMICACINA", 2222),
            _tested("SEM MAPEAMENTO", None),
            _tested("CEFEPIME", 3333),
        ]

        assert culture_service.culture_sctids(cultures) == [2222, 3333]

    def test_no_cultures(self):
        assert culture_service.culture_sctids(None) == []
