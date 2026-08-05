"""AlertProtocol class: test protocol rules against prescription data"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, Union

from models.appendix import MeasureUnit
from models.enums import DrugTypeEnum
from models.main import DrugAttributes, Substance
from models.prescription import Patient, Prescription, PrescriptionDrug
from utils import prescriptionutils
from utils.alert_protocol_trace import (
    CombinationCriterionTrace,
    CombinationDrugTrace,
    TraceReasonEnum,
    VariableTrace,
)

# Simpler regex that avoids ReDoS by using alternation without nested quantifiers
# Matches any combination of: keywords (True, False, and, or, not) OR structural chars (whitespace, parens)
SAFE_LOGICAL_EXPR_REGEX = r"^(?:True|False|and|or|not|[()\s])+$"


@dataclass
class ProtocolExtraInfo:
    segment_type: Optional[int] = None
    is_cpoe: bool = False


class AlertProtocol:
    """AlertProtocol class: test protocol rules against prescription data"""

    prescription = None
    patient = None
    drugs = None
    filtered_drugs = None
    substance_list = None
    class_list = None
    id_drug_list = None
    route_list = None
    exams = None
    exams_by_ref = None
    cn_stats = None
    protocol_variables = None
    protocol_msgs = None
    related_items = None  # list of prescriptions items who were related to the protocol being active
    protocol_extra_info: Union[ProtocolExtraInfo, None] = None
    trace_log = None  # list of VariableTrace filled when tracing is enabled

    def __init__(
        self,
        drugs: dict,
        exams: dict,
        prescription: Prescription,
        patient: Patient,
        cn_stats: dict,
        protocol_extra_info: Union[ProtocolExtraInfo, None] = None,
    ):
        self.prescription = prescription
        self.patient = patient
        self.drugs = drugs
        self.filtered_drugs = self._filter_drug_list()
        self.exams = exams
        self.exams_by_ref = {}
        for exam_data in exams.values():
            if not exam_data or not isinstance(exam_data, dict):
                continue
            ref = exam_data.get("tp_exam_ref")
            if ref is None:
                continue
            existing = self.exams_by_ref.get(ref)
            if existing is None:
                self.exams_by_ref[ref] = exam_data
            else:
                new_date = exam_data.get("date")
                existing_date = existing.get("date")
                if new_date is not None and (
                    existing_date is None or new_date > existing_date
                ):
                    self.exams_by_ref[ref] = exam_data

        self.cn_stats = cn_stats

        self.substance_list = []
        self.class_list = []
        self.id_drug_list = []
        self.route_list = []
        self.protocol_variables = {}
        self.protocol_msgs = []
        self.related_items = []
        self.protocol_extra_info = protocol_extra_info if protocol_extra_info else None

        self._trace_enabled = False
        self.trace_log = []
        self._current_trace = None
        self._last_substituted_trigger = None

        # fill lists
        for d in self.filtered_drugs:
            prescription_drug: PrescriptionDrug = d[0]
            substance: Substance = d[11]

            if prescription_drug.idDrug:
                self.id_drug_list.append(str(prescription_drug.idDrug))

            if prescription_drug.route:
                self.route_list.append(prescription_drug.route.upper())

            if substance:
                self.substance_list.append(str(substance.id))

            if substance and substance.idclass:
                self.class_list.append(substance.idclass)

    def get_protocol_alerts(self, protocol: dict):
        """get configured protocol alerts"""

        self.protocol_variables = {}
        self.protocol_msgs = []
        self.related_items = []

        for v in protocol.get("variables", []):
            if self._trace_enabled:
                self._current_trace = VariableTrace(
                    name=v.get("name"),
                    field=v.get("field"),
                    operator=v.get("operator"),
                    expected_value=v.get("value"),
                )

            self.protocol_variables[v.get("name")] = self._fill_variable(variable=v)

            if self._trace_enabled and self._current_trace is not None:
                self._current_trace.result = self.protocol_variables[v.get("name")]
                self.trace_log.append(self._current_trace)
                self._current_trace = None

            fail_msg = v.get("message", {})
            if fail_msg.get("if", None) == self.protocol_variables[v.get("name")]:
                self.protocol_msgs.append(fail_msg.get("then"))

        trigger = protocol.get("trigger")
        for var, value in self.protocol_variables.items():
            trigger = trigger.replace("{{" + var + "}}", str(value))

        self._last_substituted_trigger = trigger

        if not self._is_safe_logical_expression(trigger):
            raise ValueError("unsafe expression")

        safe_globals = {"__builtins__": None}
        safe_locals = {}

        if eval(trigger, safe_globals, safe_locals):  # pylint: disable=eval-used
            result = protocol.get("result", {}).copy()
            result["variableMessages"] = self.protocol_msgs
            result["related_items"] = self.related_items
            return result

        return None

    def evaluate_with_trace(self, protocol: dict) -> dict:
        """Runs get_protocol_alerts with tracing enabled and returns the result
        plus a structured evaluation trace (one VariableTrace per variable)"""

        self._trace_enabled = True
        self.trace_log = []
        try:
            result = self.get_protocol_alerts(protocol=protocol)
        finally:
            self._trace_enabled = False
            self._current_trace = None

        return {
            "activated": result is not None,
            "result": result,
            "trigger": protocol.get("trigger"),
            "substituted_trigger": self._last_substituted_trigger,
            "variables": self.trace_log,
            "related_items": list(self.related_items),
            "variable_messages": list(self.protocol_msgs),
        }

    def _trace_miss(self, reason: TraceReasonEnum, **details) -> bool:
        """Records an early-exit reason when tracing; always returns False"""

        if self._trace_enabled and self._current_trace is not None:
            self._current_trace.reason = reason.value
            self._current_trace.details.update(details)

        return False

    def _trace_compare(self, op: str, value1, value2, **details) -> bool:
        """Wraps _compare, recording actual/expected values when tracing"""

        result = self._compare(op=op, value1=value1, value2=value2)

        if self._trace_enabled and self._current_trace is not None:
            self._current_trace.reason = TraceReasonEnum.COMPARED.value
            self._current_trace.actual_value = value1
            self._current_trace.details.update(details)

            if op in ("IN", "NOTIN", "NOT IN"):
                try:
                    self._current_trace.details["matched"] = sorted(
                        set(value1) & set(value2)
                    )
                except TypeError:
                    pass

        return result

    def _combo_criterion(
        self, current: bool, criterion: str, op: str, value1, value2, drug_trace
    ) -> bool:
        """Evaluates one combination criterion preserving short-circuit semantics;
        records per-drug trace when tracing is enabled"""

        if not current:
            if drug_trace is not None:
                drug_trace.criteria.append(
                    CombinationCriterionTrace(
                        criterion=criterion,
                        operator=op,
                        expected=value2,
                        actual=None,
                        result=None,
                    )
                )
            return False

        result = self._compare(op=op, value1=value1, value2=value2)

        if drug_trace is not None:
            drug_trace.criteria.append(
                CombinationCriterionTrace(
                    criterion=criterion,
                    operator=op,
                    expected=value2,
                    actual=value1,
                    result=result,
                )
            )
            if not result and drug_trace.failed_criterion is None:
                drug_trace.failed_criterion = criterion

        return result

    def _fill_variable(self, variable: dict):
        field = variable.get("field", None)
        operator = variable.get("operator")
        value = variable.get("value")

        if field == "substance":
            value = [str(v) for v in value]
            return self._trace_compare(
                op=operator, value1=self.substance_list, value2=value
            )

        if field == "class":
            return self._trace_compare(
                op=operator, value1=self.class_list, value2=value
            )

        if field == "idDrug":
            value = [str(v) for v in value]
            return self._trace_compare(
                op=operator, value1=self.id_drug_list, value2=value
            )

        if field == "route":
            return self._trace_compare(
                op=operator, value1=self.route_list, value2=value
            )

        if field == "cn_stats":
            stats_type = variable.get("statsType")
            if stats_type not in self.cn_stats:
                return self._trace_miss(
                    TraceReasonEnum.STAT_NOT_FOUND, statsType=stats_type
                )

            if self.cn_stats.get(stats_type, None) is None:
                return self._trace_miss(
                    TraceReasonEnum.STAT_NOT_FOUND, statsType=stats_type
                )

            try:
                stats_value = int(self.cn_stats.get(stats_type))
                value = int(value)
            except ValueError:
                return self._trace_miss(
                    TraceReasonEnum.VALUE_NOT_NUMERIC, statsType=stats_type
                )

            return self._trace_compare(
                op=operator, value1=stats_value, value2=value, statsType=stats_type
            )

        if field == "exam":
            exam_type = variable.get("examType")
            exam_period = variable.get("examPeriod", None)

            if exam_type not in self.exams:
                return self._trace_miss(
                    TraceReasonEnum.EXAM_NOT_FOUND, examType=exam_type
                )

            if self.exams[exam_type]["value"] is None:
                return self._trace_miss(
                    TraceReasonEnum.EXAM_VALUE_MISSING, examType=exam_type
                )

            if exam_period is not None:
                try:
                    exam_date = date.fromisoformat(
                        self.exams[exam_type]["date"].split("T")[0]
                    )
                    days_diff = (date.today() - exam_date).days

                    if int(days_diff) > int(exam_period):
                        return self._trace_miss(
                            TraceReasonEnum.EXAM_EXPIRED,
                            examType=exam_type,
                            examDate=exam_date.isoformat(),
                            daysDiff=days_diff,
                            examPeriod=exam_period,
                        )
                except (ValueError, KeyError):
                    return self._trace_miss(
                        TraceReasonEnum.EXAM_DATE_INVALID, examType=exam_type
                    )

            try:
                exam_value = float(self.exams[exam_type]["value"])
                value = float(value)
            except ValueError:
                return self._trace_miss(
                    TraceReasonEnum.VALUE_NOT_NUMERIC, examType=exam_type
                )

            return self._trace_compare(
                op=operator,
                value1=exam_value,
                value2=value,
                examType=exam_type,
                examDate=self.exams[exam_type].get("date"),
            )

        if field == "exam_ref":
            exam_type = variable.get("examRefType")
            exam_period = variable.get("examRefPeriod", None)

            if not self.exams_by_ref:
                return self._trace_miss(
                    TraceReasonEnum.EXAM_NOT_FOUND, examType=exam_type
                )

            if exam_type not in self.exams_by_ref:
                return self._trace_miss(
                    TraceReasonEnum.EXAM_NOT_FOUND, examType=exam_type
                )

            if self.exams_by_ref[exam_type]["value"] is None:
                return self._trace_miss(
                    TraceReasonEnum.EXAM_VALUE_MISSING, examType=exam_type
                )

            if exam_period is not None:
                try:
                    exam_date = date.fromisoformat(
                        self.exams_by_ref[exam_type]["date"].split("T")[0]
                    )
                    days_diff = (date.today() - exam_date).days

                    if int(days_diff) > int(exam_period):
                        return self._trace_miss(
                            TraceReasonEnum.EXAM_EXPIRED,
                            examType=exam_type,
                            examDate=exam_date.isoformat(),
                            daysDiff=days_diff,
                            examPeriod=exam_period,
                        )
                except (ValueError, KeyError):
                    return self._trace_miss(
                        TraceReasonEnum.EXAM_DATE_INVALID, examType=exam_type
                    )

            try:
                exam_value = float(self.exams_by_ref[exam_type]["value"])
                value = float(value)
            except ValueError:
                return self._trace_miss(
                    TraceReasonEnum.VALUE_NOT_NUMERIC, examType=exam_type
                )

            return self._trace_compare(
                op=operator,
                value1=exam_value,
                value2=value,
                examType=exam_type,
                examDate=self.exams_by_ref[exam_type].get("date"),
            )

        if field == "admissionTime":
            if not self.patient:
                return self._trace_miss(TraceReasonEnum.NO_PATIENT)

            if not self.patient.admissionDate:
                return self._trace_miss(TraceReasonEnum.NO_ADMISSION_DATE)

            hours_diff = (
                datetime.now() - self.patient.admissionDate
            ).total_seconds() / 3600

            try:
                value = float(value)
            except ValueError:
                return self._trace_miss(TraceReasonEnum.VALUE_NOT_NUMERIC)

            return self._trace_compare(
                op=operator,
                value1=hours_diff,
                value2=value,
                admissionDate=self.patient.admissionDate.isoformat(),
            )

        if field == "stConcilia":
            if not self.patient:
                return self._trace_miss(TraceReasonEnum.NO_PATIENT)

            st_concilia = (
                self.patient.st_conciliation
                if self.patient.st_conciliation is not None
                else 0
            )

            try:
                value = int(value)
            except ValueError:
                return self._trace_miss(TraceReasonEnum.VALUE_NOT_NUMERIC)

            return self._trace_compare(op=operator, value1=st_concilia, value2=value)

        if field == "age":
            age = self.exams.get("age", None)
            if not age:
                return self._trace_miss(TraceReasonEnum.AGE_MISSING)

            try:
                age = float(age)
                value = float(value)
            except ValueError:
                return self._trace_miss(TraceReasonEnum.VALUE_NOT_NUMERIC)

            return self._trace_compare(op=operator, value1=age, value2=value)

        if field == "weight":
            weight = self.exams.get("weight", None)
            if not weight:
                return self._trace_miss(TraceReasonEnum.WEIGHT_MISSING)
            try:
                weight = float(weight)
                value = float(value)
            except ValueError:
                return self._trace_miss(TraceReasonEnum.VALUE_NOT_NUMERIC)

            return self._trace_compare(op=operator, value1=weight, value2=value)

        if field == "imc":
            weight = self.exams.get("weight", None)
            height = self.exams.get("height", None)
            if not weight:
                return self._trace_miss(TraceReasonEnum.WEIGHT_MISSING)
            if not height:
                return self._trace_miss(TraceReasonEnum.HEIGHT_MISSING)

            try:
                weight = float(weight)
                height = float(height)
                value = float(value)
            except ValueError:
                return self._trace_miss(TraceReasonEnum.VALUE_NOT_NUMERIC)

            if height <= 0:
                return self._trace_miss(TraceReasonEnum.HEIGHT_MISSING)

            # height is stored in cm
            imc = round(weight / pow(height / 100, 2), 2)

            return self._trace_compare(op=operator, value1=imc, value2=value)

        if field == "segmentType":
            if (
                self.protocol_extra_info is None
                or self.protocol_extra_info.segment_type is None
            ):
                return self._trace_miss(TraceReasonEnum.NO_SEGMENT_TYPE)

            if operator in ["IN", "NOT IN"]:
                segment_type = [self.protocol_extra_info.segment_type]
                value = [int(v) for v in value]
            else:
                segment_type = self.protocol_extra_info.segment_type

            return self._trace_compare(op=operator, value1=segment_type, value2=value)

        if field == "idDepartment":
            if operator in ["IN", "NOT IN"]:
                department = [str(self.prescription.idDepartment)]
                value = [str(v) for v in value]
            else:
                department = self.prescription.idDepartment

            return self._trace_compare(op=operator, value1=department, value2=value)

        if field == "idIcd":
            if operator in ["IN", "NOT IN"]:
                id_icd = [str(self.patient.id_icd).lower()]
                value = [str(v).lower() for v in value]
            else:
                return self._trace_miss(
                    TraceReasonEnum.OPERATOR_NOT_SUPPORTED, operator=operator
                )

            return self._trace_compare(op=operator, value1=id_icd, value2=value)

        if field == "dischargeReason":
            return self._trace_compare(
                op="CONTAINS", value1=self.patient.dischargeReason, value2=value
            )

        if field == "insurance":
            if self.prescription is None or self.prescription.insurance is None:
                return self._trace_miss(TraceReasonEnum.INSURANCE_MISSING)

            return self._trace_compare(
                op="CONTAINS", value1=self.prescription.insurance, value2=value
            )

        if field == "idSegment":
            if operator in ["IN", "NOT IN"]:
                segment = [str(self.prescription.idSegment)]
                value = [str(v) for v in value]
            else:
                segment = self.prescription.idSegment

            return self._trace_compare(op=operator, value1=segment, value2=value)

        if field == "combination":
            v_substance = variable.get("substance", None)
            v_drug = variable.get("drug", None)
            v_class = variable.get("class", None)

            v_dose = variable.get("dose", None)
            v_dose_op = variable.get("doseOperator", "=")

            v_frequencyday = variable.get("frequencyday", None)
            v_frequency_op = variable.get("frequencydayOperator", "=")

            v_period = variable.get("period", None)
            v_period_op = variable.get("periodOperator", "=")

            v_route = variable.get("route", None)

            v_observation = variable.get("observation", None)

            v_intravenous = variable.get("intravenous", None)
            v_feeding_tube = variable.get("feedingTube", None)

            v_default_measure_unit = variable.get("defaultMeasureUnit", None)

            v_drug_attribute = variable.get("drugAttribute", None)

            found = False
            for d in self.filtered_drugs:
                prescription_drug: PrescriptionDrug = d[0]
                substance: Substance = d[11]
                measure_unit: MeasureUnit = d[2]
                drug_attributes: DrugAttributes = d[6]
                period_cpoe = d.period_cpoe
                drug_attr_keys = self._get_drug_attribute_keys(drug_attributes)

                drug_trace = None
                if self._trace_enabled and self._current_trace is not None:
                    drug_trace = CombinationDrugTrace(
                        id_prescription_drug=prescription_drug.id,
                        id_drug=prescription_drug.idDrug,
                        drug_name=d[1].name if d[1] is not None else None,
                    )
                    self._current_trace.drugs.append(drug_trace)

                exp_result = True

                if v_substance is not None:
                    exp_result = self._combo_criterion(
                        current=exp_result,
                        criterion="substance",
                        op="IN",
                        value1=[str(substance.id)] if substance else [],
                        value2=v_substance,
                        drug_trace=drug_trace,
                    )

                if v_drug is not None:
                    exp_result = self._combo_criterion(
                        current=exp_result,
                        criterion="drug",
                        op="IN",
                        value1=[str(prescription_drug.idDrug)],
                        value2=v_drug,
                        drug_trace=drug_trace,
                    )

                if v_class is not None:
                    exp_result = self._combo_criterion(
                        current=exp_result,
                        criterion="class",
                        op="IN",
                        value1=[str(substance.idclass)] if substance else [],
                        value2=v_class,
                        drug_trace=drug_trace,
                    )

                if v_dose is not None:
                    try:
                        v_dose = float(v_dose)
                    except ValueError:
                        return self._trace_miss(
                            TraceReasonEnum.VALUE_NOT_NUMERIC, criterion="dose"
                        )

                    exp_result = self._combo_criterion(
                        current=exp_result,
                        criterion="dose",
                        op=v_dose_op,
                        value1=prescription_drug.doseconv
                        if prescription_drug.doseconv is not None
                        else 0,
                        value2=v_dose,
                        drug_trace=drug_trace,
                    )

                if v_frequencyday is not None:
                    try:
                        v_frequencyday = float(v_frequencyday)
                    except ValueError:
                        return self._trace_miss(
                            TraceReasonEnum.VALUE_NOT_NUMERIC, criterion="frequencyday"
                        )

                    exp_result = self._combo_criterion(
                        current=exp_result,
                        criterion="frequencyday",
                        op=v_frequency_op,
                        value1=prescription_drug.frequency,
                        value2=v_frequencyday,
                        drug_trace=drug_trace,
                    )

                if v_intravenous is not None:
                    intravenous_value = (
                        prescription_drug.intravenous
                        if prescription_drug.intravenous is not None
                        else False
                    )

                    exp_result = self._combo_criterion(
                        current=exp_result,
                        criterion="intravenous",
                        op="=",
                        value1=intravenous_value,
                        value2=bool(v_intravenous),
                        drug_trace=drug_trace,
                    )

                if v_feeding_tube is not None:
                    feeding_tube_value = (
                        prescription_drug.tube
                        if prescription_drug.tube is not None
                        else False
                    )

                    exp_result = self._combo_criterion(
                        current=exp_result,
                        criterion="feedingTube",
                        op="=",
                        value1=feeding_tube_value,
                        value2=bool(v_feeding_tube),
                        drug_trace=drug_trace,
                    )

                if v_default_measure_unit is not None:
                    if measure_unit is None:
                        return self._trace_miss(
                            TraceReasonEnum.MEASURE_UNIT_MISSING,
                            criterion="defaultMeasureUnit",
                        )

                    exp_result = self._combo_criterion(
                        current=exp_result,
                        criterion="defaultMeasureUnit",
                        op="=",
                        value1=measure_unit.measureunit_nh,
                        value2=v_default_measure_unit,
                        drug_trace=drug_trace,
                    )

                if v_period is not None:
                    try:
                        v_period = int(v_period)
                    except ValueError:
                        return self._trace_miss(
                            TraceReasonEnum.VALUE_NOT_NUMERIC, criterion="period"
                        )

                    _, item_period = prescriptionutils.get_prescription_item_period(
                        is_cpoe=self.protocol_extra_info.is_cpoe
                        if self.protocol_extra_info
                        else False,
                        item_period=prescription_drug.period,
                        cpoe_period=period_cpoe,
                    )

                    exp_result = self._combo_criterion(
                        current=exp_result,
                        criterion="period",
                        op=v_period_op,
                        value1=item_period,
                        value2=v_period,
                        drug_trace=drug_trace,
                    )

                if v_route is not None:
                    exp_result = self._combo_criterion(
                        current=exp_result,
                        criterion="route",
                        op="IN",
                        value1=[prescription_drug.route],
                        value2=v_route,
                        drug_trace=drug_trace,
                    )

                if v_observation is not None:
                    exp_result = self._combo_criterion(
                        current=exp_result,
                        criterion="observation",
                        op="CONTAINS",
                        value1=prescription_drug.notes,
                        value2=v_observation,
                        drug_trace=drug_trace,
                    )

                if v_drug_attribute is not None and len(v_drug_attribute) > 0:
                    exp_result = self._combo_criterion(
                        current=exp_result,
                        criterion="drugAttribute",
                        op="IN",
                        value1=drug_attr_keys,
                        value2=v_drug_attribute,
                        drug_trace=drug_trace,
                    )

                if drug_trace is not None:
                    drug_trace.matched = exp_result

                if exp_result:
                    found = True
                    self.related_items.append(prescription_drug.id)

            if self._trace_enabled and self._current_trace is not None:
                self._current_trace.reason = (
                    TraceReasonEnum.COMBINATION_MATCHED.value
                    if found
                    else TraceReasonEnum.COMBINATION_NO_MATCH.value
                )

            return found

        raise NotImplementedError("field not supported")

    def _compare(self, op: str, value1, value2):
        if op == "<":
            return value1 < value2
        if op == ">":
            return value1 > value2
        if op == "=":
            return value1 == value2
        if op == "!=":
            return value1 != value2
        if op == ">=":
            return value1 >= value2
        if op == "<=":
            return value1 <= value2
        if op == "IN":
            return len(set.intersection(set(value1), set(value2))) > 0
        if op == "NOTIN":
            return len(set.intersection(set(value1), set(value2))) == 0
        if op == "CONTAINS":
            if value1 is None or value2 is None:
                return False

            return str(value2).lower() in str(value1).lower()

        raise NotImplementedError(f"operator not supported: {op}")

    def _filter_drug_list(self):
        filtered_list = []
        valid_sources = [
            DrugTypeEnum.DRUG.value,
            DrugTypeEnum.SOLUTION.value,
            DrugTypeEnum.PROCEDURE.value,
            DrugTypeEnum.DIET.value,
        ]

        for item in self.drugs:
            prescription_drug: PrescriptionDrug = item[0]

            if prescription_drug.source not in valid_sources:
                continue

            if prescription_drug.suspendedDate is not None:
                continue

            filtered_list.append(item)

        return filtered_list

    def _is_safe_logical_expression(self, expr: str) -> bool:
        """Validates if the expression contains only safe logical operators and values"""

        # Additional checks: non-empty, length limit, and regex validation
        if not expr or len(expr) >= 500:
            return False

        # Verify expression contains only safe tokens
        if not re.fullmatch(SAFE_LOGICAL_EXPR_REGEX, expr):
            return False

        # Ensure at least one keyword is present (not just whitespace/parens)
        if not re.search(r"\b(?:True|False|and|or|not)\b", expr):
            return False

        return True

    def _get_drug_attribute_keys(self, drug_attributes: DrugAttributes) -> list[str]:
        drug_attr_keys = []

        if drug_attributes is not None:
            if drug_attributes.antimicro is not None and drug_attributes.antimicro:
                drug_attr_keys.append("antimicro")

            if drug_attributes.controlled is not None and drug_attributes.controlled:
                drug_attr_keys.append("controlled")

            if drug_attributes.chemo is not None and drug_attributes.chemo:
                drug_attr_keys.append("chemo")

            if drug_attributes.mav is not None and drug_attributes.mav:
                drug_attr_keys.append("mav")

            if drug_attributes.notdefault is not None and drug_attributes.notdefault:
                drug_attr_keys.append("notdefault")

            if drug_attributes.elderly is not None and drug_attributes.elderly:
                drug_attr_keys.append("elderly")

            if drug_attributes.dialyzable is not None and drug_attributes.dialyzable:
                drug_attr_keys.append("dialyzable")

        return drug_attr_keys
