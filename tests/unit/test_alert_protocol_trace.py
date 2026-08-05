"""Test: protocol evaluation tracing (evaluate_with_trace + PT messages)"""

from datetime import date, timedelta

from models.prescription import Patient, Prescription
from tests.utils import utils_test_prescription
from utils.alert_protocol import AlertProtocol
from utils.alert_protocol_trace import (
    CombinationCriterionTrace,
    CombinationDrugTrace,
    TraceReasonEnum,
    VariableTrace,
    build_summary,
    build_variable_message,
    variable_trace_to_dict,
)


def _get_alert_protocol(drug_list=None, exams=None, cn_stats=None):
    """Builds an AlertProtocol instance with minimal mock data"""

    prescription = Prescription()
    prescription.idDepartment = 100

    patient = Patient()

    return AlertProtocol(
        drugs=drug_list if drug_list is not None else [],
        exams=exams if exams is not None else {},
        prescription=prescription,
        patient=patient,
        cn_stats=cn_stats if cn_stats is not None else {},
    )


def _folfox_drug_list():
    return [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=1,
            dose=10,
            drug_name="FLUOROURACIL",
            drug_class="Q1",
            sctid="FLUOROURACIL",
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=2,
            dose=20,
            drug_name="OXALIPLATINA",
            drug_class="Q1",
            sctid="OXALIPLATINA",
        ),
    ]


def test_trace_activated():
    """Protocol trace: activated protocol exposes per-variable results and trigger"""

    protocol = {
        "variables": [
            {
                "name": "v1",
                "field": "substance",
                "operator": "IN",
                "value": ["FLUOROURACIL"],
            },
            {
                "name": "v2",
                "field": "substance",
                "operator": "IN",
                "value": ["OXALIPLATINA"],
            },
            {
                "name": "v3",
                "field": "substance",
                "operator": "IN",
                "value": ["DEXAMETASONA"],
            },
        ],
        "trigger": "{{v1}} and ({{v2}} or {{v3}})",
        "result": {"type": "SHOW_MESSAGE", "level": "high", "message": "FOLFOX"},
    }

    alert_protocol = _get_alert_protocol(drug_list=_folfox_drug_list())
    trace = alert_protocol.evaluate_with_trace(protocol=protocol)

    assert trace["activated"] is True
    assert trace["result"] is not None
    assert trace["trigger"] == "{{v1}} and ({{v2}} or {{v3}})"
    assert trace["substituted_trigger"] == "True and (True or False)"

    variables = trace["variables"]
    assert len(variables) == 3

    v1 = variables[0]
    assert v1.name == "v1"
    assert v1.result is True
    assert v1.reason == TraceReasonEnum.COMPARED.value
    assert "FLUOROURACIL" in v1.actual_value
    assert v1.details["matched"] == ["FLUOROURACIL"]

    v3 = variables[2]
    assert v3.result is False
    assert v3.reason == TraceReasonEnum.COMPARED.value
    assert v3.details["matched"] == []


def test_trace_not_activated():
    """Protocol trace: non-activated protocol identifies the false variable"""

    protocol = {
        "variables": [
            {
                "name": "v1",
                "field": "substance",
                "operator": "IN",
                "value": ["FLUOROURACIL"],
            },
            {
                "name": "v3",
                "field": "substance",
                "operator": "IN",
                "value": ["DEXAMETASONA"],
            },
        ],
        "trigger": "{{v1}} and {{v3}}",
        "result": {"type": "SHOW_MESSAGE", "level": "high", "message": "test"},
    }

    alert_protocol = _get_alert_protocol(drug_list=_folfox_drug_list())
    trace = alert_protocol.evaluate_with_trace(protocol=protocol)

    assert trace["activated"] is False
    assert trace["result"] is None
    assert trace["substituted_trigger"] == "True and False"

    false_variables = [v for v in trace["variables"] if not v.result]
    assert len(false_variables) == 1
    assert false_variables[0].name == "v3"


def test_trace_exam_missing_and_expired():
    """Protocol trace: missing exam and expired exam produce distinct reasons"""

    exams = {
        "tgp": {
            "value": 50,
            "date": (date.today() - timedelta(days=10)).isoformat(),
        },
    }

    protocol = {
        "variables": [
            {
                "name": "tgo_alto",
                "field": "exam",
                "examType": "tgo",
                "operator": ">",
                "value": 40,
            },
            {
                "name": "tgp_alto",
                "field": "exam",
                "examType": "tgp",
                "examPeriod": 3,
                "operator": ">",
                "value": 40,
            },
        ],
        "trigger": "{{tgo_alto}} and {{tgp_alto}}",
        "result": {"type": "SHOW_MESSAGE", "level": "high", "message": "test"},
    }

    alert_protocol = _get_alert_protocol(exams=exams)
    trace = alert_protocol.evaluate_with_trace(protocol=protocol)

    assert trace["activated"] is False

    tgo = trace["variables"][0]
    assert tgo.result is False
    assert tgo.reason == TraceReasonEnum.EXAM_NOT_FOUND.value
    assert tgo.details["examType"] == "tgo"

    tgp = trace["variables"][1]
    assert tgp.result is False
    assert tgp.reason == TraceReasonEnum.EXAM_EXPIRED.value
    assert tgp.details["daysDiff"] == 10
    assert tgp.details["examPeriod"] == 3


def test_trace_combination_per_drug():
    """Protocol trace: combination variables expose per-drug criteria detail"""

    drug_list = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=1,
            dose=10,
            drug_name="Drug A",
            drug_class="J1",
            route="ORAL",
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=2,
            dose=200,
            drug_name="Drug B",
            drug_class="J1",
            route="IV",
        ),
    ]

    protocol = {
        "variables": [
            {
                "name": "v1",
                "field": "combination",
                "class": ["J1"],
                "dose": 100,
                "doseOperator": ">",
                "route": ["IV"],
            },
        ],
        "trigger": "{{v1}}",
        "result": {"type": "SHOW_MESSAGE", "level": "high", "message": "test"},
    }

    alert_protocol = _get_alert_protocol(drug_list=drug_list)
    trace = alert_protocol.evaluate_with_trace(protocol=protocol)

    assert trace["activated"] is True
    assert trace["related_items"] == [2]

    variable = trace["variables"][0]
    assert variable.reason == TraceReasonEnum.COMBINATION_MATCHED.value
    assert len(variable.drugs) == 2

    drug_a = variable.drugs[0]
    assert drug_a.drug_name == "Drug A"
    assert drug_a.matched is False
    assert drug_a.failed_criterion == "dose"
    # criteria order: class, dose, route — route short-circuited
    assert drug_a.criteria[0].result is True
    assert drug_a.criteria[1].result is False
    assert drug_a.criteria[2].criterion == "route"
    assert drug_a.criteria[2].result is None
    assert drug_a.criteria[2].actual is None

    drug_b = variable.drugs[1]
    assert drug_b.matched is True
    assert drug_b.failed_criterion is None


def test_get_protocol_alerts_unchanged():
    """Protocol trace: plain get_protocol_alerts is unaffected by tracing"""

    protocol = {
        "variables": [
            {
                "name": "v1",
                "field": "substance",
                "operator": "IN",
                "value": ["FLUOROURACIL"],
            },
        ],
        "trigger": "{{v1}}",
        "result": {"type": "SHOW_MESSAGE", "level": "high", "message": "test"},
    }

    alert_protocol = _get_alert_protocol(drug_list=_folfox_drug_list())

    plain_before = alert_protocol.get_protocol_alerts(protocol=protocol)
    assert alert_protocol.trace_log == []

    trace = alert_protocol.evaluate_with_trace(protocol=protocol)
    assert trace["activated"] is True
    assert len(trace["variables"]) == 1

    plain_after = alert_protocol.get_protocol_alerts(protocol=protocol)
    assert plain_before == plain_after
    # plain call must not have appended new trace entries
    assert len(alert_protocol.trace_log) == 1


def _imc_protocol(operator: str, value):
    return {
        "variables": [
            {
                "name": "imc_elevado",
                "field": "imc",
                "operator": operator,
                "value": value,
            },
        ],
        "trigger": "{{imc_elevado}}",
        "result": {"type": "SHOW_MESSAGE", "level": "high", "message": "test"},
    }


def test_trace_imc_computed():
    """Protocol trace: imc is computed from weight and height (kg / m²)"""

    alert_protocol = _get_alert_protocol(exams={"weight": 80, "height": 170})

    trace = alert_protocol.evaluate_with_trace(protocol=_imc_protocol(">", 25))

    variable = alert_protocol.trace_log[0]
    assert variable.field == "imc"
    assert variable.reason == TraceReasonEnum.COMPARED.value
    # 80 / (1.70 ** 2) = 27.68
    assert variable.actual_value == 27.68
    assert variable.result is True
    assert trace["activated"] is True

    assert build_variable_message(variable) == (
        "Variável 'imc_elevado' (IMC (kg/m²)): o valor encontrado foi 27.68; "
        "esperado: maior que 25 → verdadeiro"
    )


def test_trace_imc_below_threshold():
    """Protocol trace: imc comparison evaluates to false when below the threshold"""

    alert_protocol = _get_alert_protocol(exams={"weight": 50, "height": 180})

    trace = alert_protocol.evaluate_with_trace(protocol=_imc_protocol(">", 25))

    variable = alert_protocol.trace_log[0]
    assert variable.reason == TraceReasonEnum.COMPARED.value
    # 50 / (1.80 ** 2) = 15.43
    assert variable.actual_value == 15.43
    assert variable.result is False
    assert trace["activated"] is False


def test_trace_imc_missing_data():
    """Protocol trace: imc reports which patient measure is missing"""

    no_height = _get_alert_protocol(exams={"weight": 80})
    no_height.evaluate_with_trace(protocol=_imc_protocol(">", 25))
    variable = no_height.trace_log[0]
    assert variable.reason == TraceReasonEnum.HEIGHT_MISSING.value
    assert variable.result is False
    assert build_variable_message(variable) == (
        "Variável 'imc_elevado' (IMC (kg/m²)): o paciente não possui altura "
        "registrada → falso (dado indisponível)"
    )

    no_weight = _get_alert_protocol(exams={"height": 170})
    no_weight.evaluate_with_trace(protocol=_imc_protocol(">", 25))
    assert no_weight.trace_log[0].reason == TraceReasonEnum.WEIGHT_MISSING.value

    # a zero height must not raise ZeroDivisionError
    zero_height = _get_alert_protocol(exams={"weight": 80, "height": "0"})
    zero_height.evaluate_with_trace(protocol=_imc_protocol(">", 25))
    assert zero_height.trace_log[0].reason == TraceReasonEnum.HEIGHT_MISSING.value


def test_pt_messages():
    """Protocol trace: Portuguese message builder output"""

    substance_in = VariableTrace(
        name="possui_fluorouracil",
        field="substance",
        operator="IN",
        expected_value=["7947"],
        result=True,
        reason=TraceReasonEnum.COMPARED.value,
        actual_value=["7947", "8812"],
        details={"matched": ["7947"]},
    )
    name_lookup = {"substance": {"7947": "FLUOROURACIL"}, "drug": {}}
    assert build_variable_message(substance_in, name_lookup) == (
        "Variável 'possui_fluorouracil' (substância): "
        "a prescrição contém: FLUOROURACIL → verdadeiro"
    )

    exam_missing = VariableTrace(
        name="tgo_alto",
        field="exam",
        operator=">",
        expected_value="40",
        result=False,
        reason=TraceReasonEnum.EXAM_NOT_FOUND.value,
        details={"examType": "tgo"},
    )
    assert build_variable_message(exam_missing, name_lookup) == (
        "Variável 'tgo_alto' (exame): o paciente não possui o exame 'tgo' "
        "registrado → falso (dado indisponível)"
    )

    scalar = VariableTrace(
        name="peso_baixo",
        field="weight",
        operator="<",
        expected_value=60,
        result=False,
        reason=TraceReasonEnum.COMPARED.value,
        actual_value=80.0,
    )
    assert build_variable_message(scalar, name_lookup) == (
        "Variável 'peso_baixo' (peso (kg)): o valor encontrado foi 80; "
        "esperado: menor que 60 → falso"
    )

    combination = VariableTrace(
        name="combo_dose",
        field="combination",
        result=False,
        reason=TraceReasonEnum.COMBINATION_NO_MATCH.value,
        drugs=[
            CombinationDrugTrace(
                id_prescription_drug=982,
                id_drug=77,
                drug_name="OXALIPLATINA 50MG",
                matched=False,
                failed_criterion="dose",
                criteria=[
                    CombinationCriterionTrace(
                        criterion="dose",
                        operator=">=",
                        expected=100.0,
                        actual=50.0,
                        result=False,
                    ),
                ],
            ),
        ],
    )
    combination_message = build_variable_message(combination, name_lookup)
    assert "nenhum item da prescrição atende aos critérios" in combination_message
    assert "'OXALIPLATINA 50MG' falhou no critério dose" in combination_message
    assert "encontrado: 50; esperado: maior ou igual a 100" in combination_message

    assert build_summary(
        activated=True,
        protocol_name="FOLFOX",
        substituted_trigger="True and True",
    ) == ("Protocolo 'FOLFOX' ATIVADO: o gatilho 'True and True' avaliou como verdadeiro.")

    assert build_summary(
        activated=False,
        protocol_name="FOLFOX",
        substituted_trigger="True and False",
    ) == ("Protocolo 'FOLFOX' NÃO ativado: o gatilho 'True and False' avaliou como falso.")

    # serialization includes labels and the ready-made message
    serialized = variable_trace_to_dict(substance_in, name_lookup)
    assert serialized["fieldLabel"] == "substância"
    assert serialized["operatorLabel"] == "contém pelo menos um de"
    assert serialized["message"].endswith("→ verdadeiro")
