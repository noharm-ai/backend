"""Trace structures and user-friendly messages for protocol evaluation (AlertProtocol)"""

import dataclasses
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TraceReasonEnum(Enum):
    """Enum: why a protocol variable evaluated to its result"""

    # a real comparison ran
    COMPARED = "COMPARED"
    COMBINATION_MATCHED = "COMBINATION_MATCHED"
    COMBINATION_NO_MATCH = "COMBINATION_NO_MATCH"

    # data-missing / defaulted-to-false early exits
    STAT_NOT_FOUND = "STAT_NOT_FOUND"
    EXAM_NOT_FOUND = "EXAM_NOT_FOUND"
    EXAM_VALUE_MISSING = "EXAM_VALUE_MISSING"
    EXAM_EXPIRED = "EXAM_EXPIRED"
    EXAM_DATE_INVALID = "EXAM_DATE_INVALID"
    VALUE_NOT_NUMERIC = "VALUE_NOT_NUMERIC"
    NO_PATIENT = "NO_PATIENT"
    NO_ADMISSION_DATE = "NO_ADMISSION_DATE"
    AGE_MISSING = "AGE_MISSING"
    WEIGHT_MISSING = "WEIGHT_MISSING"
    NO_SEGMENT_TYPE = "NO_SEGMENT_TYPE"
    INSURANCE_MISSING = "INSURANCE_MISSING"
    OPERATOR_NOT_SUPPORTED = "OPERATOR_NOT_SUPPORTED"
    MEASURE_UNIT_MISSING = "MEASURE_UNIT_MISSING"


@dataclass
class CombinationCriterionTrace:
    """Trace: one criterion of a combination variable tested against one drug"""

    criterion: str
    operator: str
    expected: any
    actual: any
    result: Optional[bool]  # None = not evaluated (short-circuited)


@dataclass
class CombinationDrugTrace:
    """Trace: one prescription item tested against a combination variable"""

    id_prescription_drug: int
    id_drug: int
    drug_name: Optional[str] = None
    matched: bool = False
    failed_criterion: Optional[str] = None
    criteria: list[CombinationCriterionTrace] = dataclasses.field(
        default_factory=list
    )


@dataclass
class VariableTrace:
    """Trace: evaluation record of one protocol variable"""

    name: str
    field: str
    operator: Optional[str] = None
    expected_value: any = None
    result: bool = False
    reason: str = TraceReasonEnum.COMPARED.value
    actual_value: any = None
    details: dict = dataclasses.field(default_factory=dict)
    drugs: list[CombinationDrugTrace] = dataclasses.field(
        default_factory=list
    )  # combination only


FIELD_LABELS = {
    "substance": "substância",
    "class": "classe de medicamento",
    "idDrug": "medicamento",
    "route": "via de administração",
    "cn_stats": "indicador NoHarm Care",
    "exam": "exame",
    "exam_ref": "exame (por referência)",
    "admissionTime": "tempo de internação (horas)",
    "stConcilia": "situação da conciliação",
    "age": "idade",
    "weight": "peso (kg)",
    "segmentType": "tipo de segmento",
    "idDepartment": "setor",
    "idIcd": "CID",
    "dischargeReason": "motivo de alta",
    "insurance": "convênio",
    "idSegment": "segmento",
    "combination": "combinação de critérios do item",
}

OPERATOR_LABELS = {
    "IN": "contém pelo menos um de",
    "NOTIN": "não contém nenhum de",
    "NOT IN": "não contém nenhum de",
    "CONTAINS": "contém o texto",
    ">": "maior que",
    "<": "menor que",
    ">=": "maior ou igual a",
    "<=": "menor ou igual a",
    "=": "igual a",
    "!=": "diferente de",
}

COMBINATION_CRITERION_LABELS = {
    "substance": "substância",
    "drug": "medicamento",
    "class": "classe",
    "dose": "dose",
    "frequencyday": "frequência/dia",
    "period": "período (dias)",
    "route": "via de administração",
    "observation": "observação",
    "intravenous": "intravenoso",
    "feedingTube": "sonda",
    "defaultMeasureUnit": "unidade de medida padrão",
    "drugAttribute": "atributo do medicamento",
}

# templates for early-exit reasons ("why the variable defaulted to false")
REASON_TEMPLATES = {
    TraceReasonEnum.STAT_NOT_FOUND.value: "o indicador '{statsType}' não está disponível para este paciente",
    TraceReasonEnum.EXAM_NOT_FOUND.value: "o paciente não possui o exame '{examType}' registrado",
    TraceReasonEnum.EXAM_VALUE_MISSING.value: "o exame '{examType}' não possui valor registrado",
    TraceReasonEnum.EXAM_EXPIRED.value: (
        "o exame '{examType}' mais recente é de {examDate} ({daysDiff} dias atrás), "
        "fora do período de {examPeriod} dias exigido pelo protocolo"
    ),
    TraceReasonEnum.EXAM_DATE_INVALID.value: "não foi possível interpretar a data do exame '{examType}'",
    TraceReasonEnum.VALUE_NOT_NUMERIC.value: "o valor configurado no protocolo não é numérico",
    TraceReasonEnum.NO_PATIENT.value: "não há dados do paciente disponíveis",
    TraceReasonEnum.NO_ADMISSION_DATE.value: "o paciente não possui data de internação registrada",
    TraceReasonEnum.AGE_MISSING.value: "o paciente não possui idade registrada",
    TraceReasonEnum.WEIGHT_MISSING.value: "o paciente não possui peso registrado",
    TraceReasonEnum.NO_SEGMENT_TYPE.value: "o segmento da prescrição não possui tipo definido",
    TraceReasonEnum.INSURANCE_MISSING.value: "a prescrição não possui convênio registrado",
    TraceReasonEnum.OPERATOR_NOT_SUPPORTED.value: "o operador '{operator}' não é suportado para este campo",
    TraceReasonEnum.MEASURE_UNIT_MISSING.value: "um dos itens da prescrição não possui unidade de medida padrão cadastrada",
}

# reasons caused by protocol configuration rather than missing patient data
_CONFIG_REASONS = {
    TraceReasonEnum.VALUE_NOT_NUMERIC.value,
    TraceReasonEnum.OPERATOR_NOT_SUPPORTED.value,
}

_LIST_OPERATORS = {"IN", "NOTIN", "NOT IN"}


def _fmt_value(value) -> str:
    """Formats a value for display, trimming float noise"""
    if isinstance(value, bool):
        return "sim" if value else "não"
    if isinstance(value, float):
        rounded = round(value, 2)
        if rounded == int(rounded):
            return str(int(rounded))
        return str(rounded)
    return str(value)


def _translate_values(values, mapping: dict) -> list[str]:
    """Translates a list of ids to names using mapping; falls back to the raw value"""
    if values is None:
        return []
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    mapping = mapping or {}
    return [mapping.get(str(v), _fmt_value(v)) for v in values]


def _lookup_for_field(field_name: str, name_lookup: dict) -> dict:
    """Picks the id->name map applicable to a variable field"""
    name_lookup = name_lookup or {}
    if field_name in ("substance",):
        return name_lookup.get("substance", {})
    if field_name in ("idDrug", "drug"):
        return name_lookup.get("drug", {})
    return {}


def _result_suffix(result: bool) -> str:
    return " → verdadeiro" if result else " → falso"


def build_variable_message(trace: VariableTrace, name_lookup: dict = None) -> str:
    """Builds a user-friendly Portuguese sentence explaining one variable's evaluation"""

    field_label = FIELD_LABELS.get(trace.field, trace.field)
    prefix = f"Variável '{trace.name}' ({field_label}): "

    if trace.field == "combination":
        return prefix + _build_combination_body(trace, name_lookup) + _result_suffix(
            trace.result
        )

    if trace.reason in REASON_TEMPLATES:
        template = REASON_TEMPLATES[trace.reason]
        context = dict(trace.details)
        context.setdefault("operator", trace.operator)
        try:
            body = template.format(**context)
        except (KeyError, IndexError):
            body = template.replace("{", "").replace("}", "")

        note = (
            " (configuração do protocolo inválida)"
            if trace.reason in _CONFIG_REASONS
            else " (dado indisponível)"
        )
        return prefix + body + _result_suffix(trace.result) + note

    # reason == COMPARED
    return prefix + _build_compared_body(trace, name_lookup) + _result_suffix(
        trace.result
    )


def _build_compared_body(trace: VariableTrace, name_lookup: dict) -> str:
    """Body for variables where a real comparison ran"""

    mapping = _lookup_for_field(trace.field, name_lookup)
    op = trace.operator

    if op in _LIST_OPERATORS:
        expected_names = ", ".join(_translate_values(trace.expected_value, mapping))
        matched_names = ", ".join(
            _translate_values(trace.details.get("matched", []), mapping)
        )

        if op == "IN":
            if trace.result:
                return f"a prescrição contém: {matched_names}"
            return f"a prescrição não contém nenhum de: {expected_names}"

        # NOTIN / NOT IN
        if trace.result:
            return f"a prescrição não contém nenhum de: {expected_names}"
        return f"a prescrição contém: {matched_names}"

    if op == "CONTAINS" or trace.operator is None:
        actual = trace.actual_value if trace.actual_value is not None else "(vazio)"
        return (
            f"o valor encontrado foi '{actual}'; "
            f"esperado conter o texto '{_fmt_value(trace.expected_value)}'"
        )

    op_label = OPERATOR_LABELS.get(op, op)
    actual = (
        _fmt_value(trace.actual_value) if trace.actual_value is not None else "(vazio)"
    )
    return (
        f"o valor encontrado foi {actual}; "
        f"esperado: {op_label} {_fmt_value(trace.expected_value)}"
    )


def _build_combination_body(trace: VariableTrace, name_lookup: dict) -> str:
    """Body for combination variables, with per-drug detail"""

    if trace.reason in REASON_TEMPLATES:
        template = REASON_TEMPLATES[trace.reason]
        try:
            body = template.format(**trace.details)
        except (KeyError, IndexError):
            body = template.replace("{", "").replace("}", "")
        return body

    matched = [d for d in trace.drugs if d.matched]

    if matched:
        names = ", ".join(
            f"'{d.drug_name}'" if d.drug_name else f"item {d.id_prescription_drug}"
            for d in matched
        )
        count = len(matched)
        plural = "itens atendem" if count > 1 else "item atende"
        return f"{count} {plural} aos critérios: {names}"

    if not trace.drugs:
        return "não há itens de prescrição para avaliar"

    body = "nenhum item da prescrição atende aos critérios"
    example = next((d for d in trace.drugs if d.failed_criterion), None)
    if example:
        failed = next(
            (c for c in example.criteria if c.criterion == example.failed_criterion),
            None,
        )
        name = example.drug_name or f"item {example.id_prescription_drug}"
        if failed:
            criterion_label = COMBINATION_CRITERION_LABELS.get(
                failed.criterion, failed.criterion
            )
            op_label = OPERATOR_LABELS.get(failed.operator, failed.operator)
            mapping = _lookup_for_field(failed.criterion, name_lookup)
            expected = ", ".join(_translate_values(failed.expected, mapping))
            actual = ", ".join(_translate_values(failed.actual, mapping)) or "(vazio)"
            body += (
                f"; ex.: '{name}' falhou no critério {criterion_label} "
                f"(encontrado: {actual}; esperado: {op_label} {expected})"
            )

    return body


def build_summary(activated: bool, protocol_name: str, substituted_trigger: str) -> str:
    """Builds the final Portuguese verdict for a protocol evaluation"""

    if activated:
        return (
            f"Protocolo '{protocol_name}' ATIVADO: o gatilho "
            f"'{substituted_trigger}' avaliou como verdadeiro."
        )

    return (
        f"Protocolo '{protocol_name}' NÃO ativado: o gatilho "
        f"'{substituted_trigger}' avaliou como falso."
    )


def criterion_trace_to_dict(criterion: CombinationCriterionTrace) -> dict:
    """Serializes a combination criterion trace to a camelCase dict"""
    return {
        "criterion": criterion.criterion,
        "criterionLabel": COMBINATION_CRITERION_LABELS.get(
            criterion.criterion, criterion.criterion
        ),
        "operator": criterion.operator,
        "operatorLabel": OPERATOR_LABELS.get(criterion.operator, criterion.operator),
        "expected": criterion.expected,
        "actual": criterion.actual,
        "result": criterion.result,
    }


def drug_trace_to_dict(drug: CombinationDrugTrace) -> dict:
    """Serializes a combination drug trace to a camelCase dict"""
    return {
        "idPrescriptionDrug": drug.id_prescription_drug,
        "idDrug": drug.id_drug,
        "name": drug.drug_name,
        "matched": drug.matched,
        "failedCriterion": drug.failed_criterion,
        "criteria": [criterion_trace_to_dict(c) for c in drug.criteria],
    }


def variable_trace_to_dict(trace: VariableTrace, name_lookup: dict = None) -> dict:
    """Serializes a variable trace to a camelCase dict, including the PT message"""
    return {
        "name": trace.name,
        "field": trace.field,
        "fieldLabel": FIELD_LABELS.get(trace.field, trace.field),
        "operator": trace.operator,
        "operatorLabel": OPERATOR_LABELS.get(trace.operator, trace.operator),
        "expectedValue": trace.expected_value,
        "actualValue": trace.actual_value,
        "result": trace.result,
        "reason": trace.reason,
        "details": trace.details,
        "drugs": [drug_trace_to_dict(d) for d in trace.drugs],
        "message": build_variable_message(trace=trace, name_lookup=name_lookup),
    }
