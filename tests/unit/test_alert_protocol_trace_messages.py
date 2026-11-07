"""Unit tests: the Portuguese messages of the protocol trace.

When a maintainer asks why a protocol did or did not fire, every variable of
the protocol comes back with a sentence built by
``utils.alert_protocol_trace.build_variable_message``. ``test_alert_protocol_trace``
covers the trace itself and a sample of messages; this module pins down the
message branches it leaves out:

* the list operators (``NOTIN``/``NOT IN``, and ``IN`` when nothing matched),
  with ids translated to names by the lookup of the variable's field;
* ``CONTAINS`` (and a variable with no operator) with a plain text, an empty
  value and an expression;
* the early-exit templates: the operator taken from the variable, the note
  telling a protocol misconfiguration from missing patient data, and the
  fallback when the details lack a placeholder;
* combination variables: the early-exit template, matched items (with and
  without a name), no items at all, and the example of the first item that
  failed a criterion;
* the dict serialization, whose labels fall back to the raw key.
"""

from utils.alert_protocol_trace import (
    CombinationCriterionTrace,
    CombinationDrugTrace,
    TraceReasonEnum,
    VariableTrace,
    build_summary,
    build_variable_message,
    criterion_trace_to_dict,
    variable_trace_to_dict,
)

NAME_LOOKUP = {
    "substance": {"101": "SUBSTANCIA TESTE A", "102": "SUBSTANCIA TESTE B"},
    "drug": {"201": "MEDICAMENTO TESTE 10MG"},
}


def _compared(field: str, operator, expected, result: bool, **kwargs):
    """A variable trace where a real comparison ran"""
    return VariableTrace(
        name="var_teste",
        field=field,
        operator=operator,
        expected_value=expected,
        result=result,
        reason=TraceReasonEnum.COMPARED.value,
        **kwargs,
    )


def _combination(result: bool, drugs: list, reason=None, details=None):
    """A combination variable trace"""
    return VariableTrace(
        name="combo_teste",
        field="combination",
        result=result,
        reason=reason
        or (
            TraceReasonEnum.COMBINATION_MATCHED.value
            if result
            else TraceReasonEnum.COMBINATION_NO_MATCH.value
        ),
        details=details or {},
        drugs=drugs,
    )


class TestListOperators:
    """IN / NOTIN / NOT IN: ids are translated to names by the field's lookup"""

    def test_notin_true_lists_the_expected_names(self):
        """NOTIN true: none of the expected ids is in the prescription"""
        trace = _compared("substance", "NOTIN", ["101", "999"], True)

        assert build_variable_message(trace, NAME_LOOKUP) == (
            "Variável 'var_teste' (substância): a prescrição não contém nenhum "
            "de: SUBSTANCIA TESTE A, 999 → verdadeiro"
        )

    def test_notin_false_lists_what_matched(self):
        """NOTIN false: names the ids that were found, not the expected list"""
        trace = _compared(
            "substance",
            "NOTIN",
            ["101", "102"],
            False,
            details={"matched": ["102"]},
        )

        assert build_variable_message(trace, NAME_LOOKUP) == (
            "Variável 'var_teste' (substância): a prescrição contém: "
            "SUBSTANCIA TESTE B → falso"
        )

    def test_not_in_with_space_behaves_as_notin(self):
        """'NOT IN' is an alias of NOTIN"""
        trace = _compared(
            "substance", "NOT IN", ["101"], False, details={"matched": ["101"]}
        )

        assert build_variable_message(trace, NAME_LOOKUP) == (
            "Variável 'var_teste' (substância): a prescrição contém: "
            "SUBSTANCIA TESTE A → falso"
        )

    def test_in_false_lists_the_expected_names(self):
        """IN false: says which ids were looked for"""
        trace = _compared("substance", "IN", ["101", "102"], False)

        assert build_variable_message(trace, NAME_LOOKUP) == (
            "Variável 'var_teste' (substância): a prescrição não contém nenhum "
            "de: SUBSTANCIA TESTE A, SUBSTANCIA TESTE B → falso"
        )

    def test_drug_field_uses_the_drug_lookup(self):
        """idDrug variables translate ids with the drug names"""
        trace = _compared("idDrug", "IN", ["201"], True, details={"matched": ["201"]})

        assert build_variable_message(trace, NAME_LOOKUP) == (
            "Variável 'var_teste' (medicamento): a prescrição contém: "
            "MEDICAMENTO TESTE 10MG → verdadeiro"
        )

    def test_field_without_lookup_shows_raw_ids(self):
        """A field with no name map (e.g. department) shows the ids as they are"""
        trace = _compared("idDepartment", "IN", [1, 2], True, details={"matched": [2]})

        assert build_variable_message(trace, NAME_LOOKUP) == (
            "Variável 'var_teste' (setor): a prescrição contém: 2 → verdadeiro"
        )

    def test_scalar_expected_value_is_treated_as_a_list(self):
        """A single id (not a list) is still translated"""
        trace = _compared("substance", "IN", "101", False)

        assert build_variable_message(trace, NAME_LOOKUP) == (
            "Variável 'var_teste' (substância): a prescrição não contém nenhum "
            "de: SUBSTANCIA TESTE A → falso"
        )

    def test_missing_expected_value_renders_empty_not_none(self):
        """No expected value renders as an empty list, never as 'None'"""
        trace = _compared("substance", "NOTIN", None, True)

        message = build_variable_message(trace, None)

        assert "None" not in message
        assert message == (
            "Variável 'var_teste' (substância): a prescrição não contém nenhum "
            "de:  → verdadeiro"
        )


class TestContains:
    """CONTAINS (and no operator): text search in the field's value"""

    def test_plain_text(self):
        """A plain text is quoted as the expected content"""
        trace = _compared(
            "cn_stats", "CONTAINS", "sepse", True, actual_value="suspeita de sepse"
        )

        assert build_variable_message(trace, {}) == (
            "Variável 'var_teste' (indicador NoHarm Care): o valor encontrado "
            "foi 'suspeita de sepse'; esperado conter o texto 'sepse' → verdadeiro"
        )

    def test_empty_value_is_shown_as_empty(self):
        """A missing actual value reads '(vazio)'"""
        trace = _compared("cn_stats", "CONTAINS", "sepse", False)

        assert build_variable_message(trace, {}) == (
            "Variável 'var_teste' (indicador NoHarm Care): o valor encontrado "
            "foi '(vazio)'; esperado conter o texto 'sepse' → falso"
        )

    def test_no_operator_is_a_contains(self):
        """A variable with no operator is described as a CONTAINS"""
        trace = _compared("dischargeReason", None, "obito", False, actual_value="alta")

        assert build_variable_message(trace, {}) == (
            "Variável 'var_teste' (motivo de alta): o valor encontrado foi "
            "'alta'; esperado conter o texto 'obito' → falso"
        )

    def test_expression_lists_missing_terms_when_false(self):
        """An expression is described in words, plus the terms not found"""
        trace = _compared(
            "cn_stats",
            "CONTAINS",
            "febre&tosse|dispneia",
            False,
            actual_value="febre alta",
            details={"missing": ["tosse", "dispneia"]},
        )

        assert build_variable_message(trace, {}) == (
            "Variável 'var_teste' (indicador NoHarm Care): o valor encontrado "
            "foi 'febre alta'; esperado conter 'febre' e 'tosse' ou 'dispneia'; "
            "não encontrado: 'tosse', 'dispneia' → falso"
        )

    def test_expression_true_does_not_list_missing_terms(self):
        """A true expression never names terms as missing"""
        trace = _compared(
            "cn_stats",
            "CONTAINS",
            "febre|tosse",
            True,
            actual_value="febre",
            details={"missing": ["tosse"]},
        )

        assert "não encontrado" not in build_variable_message(trace, {})


class TestScalarValues:
    """Comparisons of a single value: how numbers and flags are written"""

    def test_float_noise_is_trimmed(self):
        """Floats are rounded to two places; whole numbers lose the decimals"""
        trace = _compared("imc", ">=", 30.0, False, actual_value=27.456789)

        assert build_variable_message(trace, {}) == (
            "Variável 'var_teste' (IMC (kg/m²)): o valor encontrado foi 27.46; "
            "esperado: maior ou igual a 30 → falso"
        )

    def test_booleans_are_written_in_portuguese(self):
        """True/False read as sim/não"""
        trace = _compared("tags", "!=", True, True, actual_value=False)

        assert build_variable_message(trace, {}) == (
            "Variável 'var_teste' (marcador do paciente): o valor encontrado foi "
            "não; esperado: diferente de sim → verdadeiro"
        )

    def test_unknown_operator_and_empty_value(self):
        """An operator without a label is shown raw; no value reads '(vazio)'"""
        trace = _compared("age", "~", 10, False)

        assert build_variable_message(trace, {}) == (
            "Variável 'var_teste' (idade): o valor encontrado foi (vazio); "
            "esperado: ~ 10 → falso"
        )


class TestReasonTemplates:
    """Early exits: the variable defaulted to false before any comparison"""

    def test_operator_comes_from_the_variable(self):
        """OPERATOR_NOT_SUPPORTED names the variable's operator and is a config issue"""
        trace = VariableTrace(
            name="var_teste",
            field="age",
            operator="LIKE",
            expected_value="10",
            result=False,
            reason=TraceReasonEnum.OPERATOR_NOT_SUPPORTED.value,
        )

        assert build_variable_message(trace, {}) == (
            "Variável 'var_teste' (idade): o operador 'LIKE' não é suportado "
            "para este campo → falso (configuração do protocolo inválida)"
        )

    def test_value_not_numeric_is_a_config_issue(self):
        """A non numeric protocol value blames the protocol, not the patient"""
        trace = VariableTrace(
            name="var_teste",
            field="weight",
            operator=">",
            expected_value="abc",
            result=False,
            reason=TraceReasonEnum.VALUE_NOT_NUMERIC.value,
        )

        assert build_variable_message(trace, {}).endswith(
            "→ falso (configuração do protocolo inválida)"
        )

    def test_missing_placeholder_falls_back_to_the_bare_template(self):
        """Details without the template's keys never raise: braces are dropped"""
        trace = VariableTrace(
            name="var_teste",
            field="exam",
            operator=">",
            expected_value=40,
            result=False,
            reason=TraceReasonEnum.EXAM_EXPIRED.value,
            details={"examType": "tgo"},
        )

        assert build_variable_message(trace, {}) == (
            "Variável 'var_teste' (exame): o exame 'examType' mais recente é de "
            "examDate (daysDiff dias atrás), fora do período de examPeriod dias "
            "exigido pelo protocolo → falso (dado indisponível)"
        )

    def test_unknown_field_uses_the_raw_field_name(self):
        """A field without a label is shown by its key"""
        trace = VariableTrace(
            name="var_teste",
            field="campoNovo",
            result=False,
            reason=TraceReasonEnum.NO_PATIENT.value,
        )

        assert build_variable_message(trace, {}) == (
            "Variável 'var_teste' (campoNovo): não há dados do paciente "
            "disponíveis → falso (dado indisponível)"
        )


class TestCombination:
    """Combination variables: one sentence about the prescription items"""

    def test_early_exit_template_has_no_data_note(self):
        """A combination early exit uses the template, without the note"""
        trace = _combination(
            False, [], reason=TraceReasonEnum.MEASURE_UNIT_MISSING.value
        )

        assert build_variable_message(trace, NAME_LOOKUP) == (
            "Variável 'combo_teste' (combinação de critérios do item): um dos "
            "itens da prescrição não possui unidade de medida padrão cadastrada "
            "→ falso"
        )

    def test_early_exit_template_with_missing_placeholder(self):
        """A combination template missing its detail key drops the braces"""
        trace = _combination(False, [], reason=TraceReasonEnum.STAT_NOT_FOUND.value)

        assert build_variable_message(trace, NAME_LOOKUP) == (
            "Variável 'combo_teste' (combinação de critérios do item): o "
            "indicador 'statsType' não está disponível para este paciente → falso"
        )

    def test_single_matched_item(self):
        """One matched item: singular sentence, with the item's name"""
        trace = _combination(
            True,
            [
                CombinationDrugTrace(
                    id_prescription_drug=1,
                    id_drug=201,
                    drug_name="DROGA A",
                    matched=True,
                ),
                CombinationDrugTrace(
                    id_prescription_drug=2, id_drug=202, drug_name="DROGA B"
                ),
            ],
        )

        assert build_variable_message(trace, NAME_LOOKUP) == (
            "Variável 'combo_teste' (combinação de critérios do item): 1 item "
            "atende aos critérios: 'DROGA A' → verdadeiro"
        )

    def test_several_matched_items_and_unnamed_item(self):
        """Several matches: plural, and an item without a name shows its id"""
        trace = _combination(
            True,
            [
                CombinationDrugTrace(
                    id_prescription_drug=1,
                    id_drug=201,
                    drug_name="DROGA A",
                    matched=True,
                ),
                CombinationDrugTrace(id_prescription_drug=5, id_drug=205, matched=True),
            ],
        )

        assert build_variable_message(trace, NAME_LOOKUP) == (
            "Variável 'combo_teste' (combinação de critérios do item): 2 itens "
            "atendem aos critérios: 'DROGA A', item 5 → verdadeiro"
        )

    def test_no_items(self):
        """An empty prescription has nothing to evaluate"""
        trace = _combination(False, [])

        assert build_variable_message(trace, NAME_LOOKUP) == (
            "Variável 'combo_teste' (combinação de critérios do item): não há "
            "itens de prescrição para avaliar → falso"
        )

    def test_no_match_without_failed_criterion(self):
        """No item failed a known criterion: no example is given"""
        trace = _combination(
            False,
            [CombinationDrugTrace(id_prescription_drug=1, id_drug=201)],
        )

        assert build_variable_message(trace, NAME_LOOKUP) == (
            "Variável 'combo_teste' (combinação de critérios do item): nenhum "
            "item da prescrição atende aos critérios → falso"
        )

    def test_failed_criterion_without_its_trace(self):
        """A failed criterion missing from the item's criteria gives no example"""
        trace = _combination(
            False,
            [
                CombinationDrugTrace(
                    id_prescription_drug=1,
                    id_drug=201,
                    failed_criterion="dose",
                    criteria=[],
                )
            ],
        )

        assert build_variable_message(trace, NAME_LOOKUP).endswith(
            "nenhum item da prescrição atende aos critérios → falso"
        )

    def test_example_translates_substances_and_empty_actual(self):
        """The example uses the substance names and shows an empty value"""
        trace = _combination(
            False,
            [
                # an item that failed nothing is skipped as the example
                CombinationDrugTrace(id_prescription_drug=8, id_drug=208),
                CombinationDrugTrace(
                    id_prescription_drug=9,
                    id_drug=209,
                    failed_criterion="substance",
                    criteria=[
                        CombinationCriterionTrace(
                            criterion="substance",
                            operator="IN",
                            expected=["101"],
                            actual=None,
                            result=False,
                        )
                    ],
                ),
            ],
        )

        assert build_variable_message(trace, NAME_LOOKUP) == (
            "Variável 'combo_teste' (combinação de critérios do item): nenhum "
            "item da prescrição atende aos critérios; ex.: 'item 9' falhou no "
            "critério substância (encontrado: (vazio); esperado: contém pelo "
            "menos um de SUBSTANCIA TESTE A) → falso"
        )

    def test_example_describes_a_contains_expression(self):
        """A CONTAINS expression in the failed criterion is described in words"""
        trace = _combination(
            False,
            [
                CombinationDrugTrace(
                    id_prescription_drug=3,
                    id_drug=203,
                    drug_name="DROGA C",
                    failed_criterion="observation",
                    criteria=[
                        CombinationCriterionTrace(
                            criterion="observation",
                            operator="CONTAINS",
                            expected="jejum|dieta zero",
                            actual="sem observacao",
                            result=False,
                        )
                    ],
                )
            ],
        )

        assert build_variable_message(trace, NAME_LOOKUP) == (
            "Variável 'combo_teste' (combinação de critérios do item): nenhum "
            "item da prescrição atende aos critérios; ex.: 'DROGA C' falhou no "
            "critério observação (encontrado: sem observacao; esperado: contém "
            "o texto 'jejum' ou 'dieta zero') → falso"
        )


class TestSerialization:
    """Dicts returned by the trace endpoint"""

    def test_criterion_labels_fall_back_to_raw_keys(self):
        """Unknown criterion and operator keep their raw keys as labels"""
        criterion = CombinationCriterionTrace(
            criterion="novoCriterio",
            operator="~",
            expected=1,
            actual=2,
            result=None,
        )

        assert criterion_trace_to_dict(criterion) == {
            "criterion": "novoCriterio",
            "criterionLabel": "novoCriterio",
            "operator": "~",
            "operatorLabel": "~",
            "expected": 1,
            "actual": 2,
            "result": None,
        }

    def test_variable_dict_carries_the_message_and_drugs(self):
        """The variable dict nests the drugs and embeds the PT message"""
        trace = _combination(
            True,
            [
                CombinationDrugTrace(
                    id_prescription_drug=1,
                    id_drug=201,
                    drug_name="DROGA A",
                    matched=True,
                    criteria=[
                        CombinationCriterionTrace(
                            criterion="dose",
                            operator=">=",
                            expected=10,
                            actual=20,
                            result=True,
                        )
                    ],
                )
            ],
        )

        result = variable_trace_to_dict(trace, NAME_LOOKUP)

        assert result["fieldLabel"] == "combinação de critérios do item"
        assert result["operatorLabel"] is None
        assert result["drugs"][0]["name"] == "DROGA A"
        assert result["drugs"][0]["criteria"][0]["criterionLabel"] == "dose"
        assert result["drugs"][0]["criteria"][0]["operatorLabel"] == (
            "maior ou igual a"
        )
        assert result["message"] == build_variable_message(trace, NAME_LOOKUP)

    def test_summary_verdicts(self):
        """The final verdict says whether the protocol fired"""
        assert build_summary(True, "Protocolo X", "(true)") == (
            "Protocolo 'Protocolo X' ATIVADO: o gatilho '(true)' avaliou como "
            "verdadeiro."
        )
        assert build_summary(False, "Protocolo X", "(false)") == (
            "Protocolo 'Protocolo X' NÃO ativado: o gatilho '(false)' avaliou "
            "como falso."
        )
