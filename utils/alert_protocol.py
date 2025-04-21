"""AlertProtocol class: test protocol rules against prescription data"""

import re
from datetime import date

from models.enums import DrugTypeEnum
from models.main import Substance
from models.prescription import PrescriptionDrug, Prescription

SAFE_LOGICAL_EXPR_REGEX = r"^\s*(?:True|False|\(|\)|and|or|not|\s+)+\s*$"


class AlertProtocol:
    """AlertProtocol class: test protocol rules against prescription data"""

    prescription = None
    drugs = None
    filtered_drugs = None
    substance_list = None
    class_list = None
    id_drug_list = None
    route_list = None
    exams = None
    protocol_variables = None
    protocol_msgs = None

    def __init__(self, drugs: dict, exams: dict, prescription: Prescription):
        self.prescription = prescription
        self.drugs = drugs
        self.filtered_drugs = self._filter_drug_list()
        self.exams = exams

        self.substance_list = []
        self.class_list = []
        self.id_drug_list = []
        self.route_list = []
        self.protocol_variables = {}
        self.protocol_msgs = []

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

        for v in protocol.get("variables", []):
            self.protocol_variables[v.get("name")] = self._fill_variable(variable=v)
            fail_msg = v.get("message", {})
            if fail_msg.get("if", None) == self.protocol_variables[v.get("name")]:
                self.protocol_msgs.append(fail_msg.get("then"))

        trigger = protocol.get("trigger")
        for var, value in self.protocol_variables.items():
            trigger = trigger.replace("{{" + var + "}}", str(value))

        if not self._is_safe_logical_expression(trigger):
            raise ValueError("unsafe expression")

        safe_globals = {"__builtins__": None}
        safe_locals = {}

        if eval(trigger, safe_globals, safe_locals):  # pylint: disable=eval-used
            result = protocol.get("result", {})
            result["variableMessages"] = self.protocol_msgs
            return result

        return None

    def _fill_variable(self, variable: dict):
        field = variable.get("field", None)
        operator = variable.get("operator")
        value = variable.get("value")

        if field == "substance":
            value = [str(v) for v in value]
            return self._compare(op=operator, value1=self.substance_list, value2=value)

        if field == "class":
            return self._compare(op=operator, value1=self.class_list, value2=value)

        if field == "idDrug":
            value = [str(v) for v in value]
            return self._compare(op=operator, value1=self.id_drug_list, value2=value)

        if field == "route":
            return self._compare(op=operator, value1=self.route_list, value2=value)

        if field == "exam":
            exam_type = variable.get("examType")
            exam_period = variable.get("examPeriod", None)

            if exam_type not in self.exams:
                return False

            if self.exams[exam_type]["value"] is None:
                return False

            if exam_period is not None:
                try:
                    exam_date = date.fromisoformat(self.exams[exam_type]["date"])
                    days_diff = (date.today() - exam_date).days

                    if int(days_diff) > int(exam_period):
                        return False
                except ValueError:
                    return False

            try:
                exam_value = float(self.exams[exam_type]["value"])
                value = float(value)
            except ValueError:
                return False

            return self._compare(op=operator, value1=exam_value, value2=value)

        if field == "age":
            age = self.exams.get("age", None)
            if not age:
                return False

            try:
                age = float(age)
                value = float(value)
            except ValueError:
                return False

            return self._compare(op=operator, value1=age, value2=value)

        if field == "weight":
            weight = self.exams.get("weight", None)
            if not weight:
                return False
            try:
                weight = float(weight)
                value = float(value)
            except ValueError:
                return False

            return self._compare(op=operator, value1=weight, value2=value)

        if field == "idDepartment":
            if operator in ["IN", "NOT IN"]:
                department = [str(self.prescription.idDepartment)]
                value = [str(v) for v in value]
            else:
                department = self.prescription.idDepartment

            return self._compare(op=operator, value1=department, value2=value)

        if field == "idSegment":
            if operator in ["IN", "NOT IN"]:
                segment = [str(self.prescription.idSegment)]
                value = [str(v) for v in value]
            else:
                segment = self.prescription.idSegment

            return self._compare(op=operator, value1=segment, value2=value)

        if field == "combination":
            v_substance = variable.get("substance", None)
            v_drug = variable.get("drug", None)
            v_class = variable.get("class", None)

            v_dose = variable.get("dose", None)
            v_dose_op = variable.get("doseOperator", None)

            v_frequencyday = variable.get("frequencyday", None)
            v_frequency_op = variable.get("frequencydayOperator", None)

            v_period = variable.get("period", None)
            v_period_op = variable.get("periodOperator", None)

            v_route = variable.get("route", None)

            found = False
            for d in self.filtered_drugs:
                prescription_drug: PrescriptionDrug = d[0]
                substance: Substance = d[11]

                exp_result = True

                if v_substance is not None:
                    exp_result = exp_result and self._compare(
                        op="IN", value1=[str(substance.id)], value2=v_substance
                    )

                if v_drug is not None:
                    exp_result = exp_result and self._compare(
                        op="IN", value1=[str(prescription_drug.idDrug)], value2=v_drug
                    )

                if v_class is not None:
                    exp_result = exp_result and self._compare(
                        op="IN", value1=[str(substance.idclass)], value2=v_class
                    )

                if v_dose is not None:
                    exp_result = exp_result and (
                        self._compare(
                            op=v_dose_op,
                            value1=prescription_drug.doseconv,
                            value2=v_dose,
                        )
                    )

                if v_frequencyday is not None:
                    exp_result = exp_result and (
                        self._compare(
                            op=v_frequency_op,
                            value1=prescription_drug.frequency,
                            value2=v_frequencyday,
                        )
                    )

                if v_period is not None:
                    exp_result = exp_result and (
                        self._compare(
                            op=v_period_op,
                            value1=prescription_drug.period,
                            value2=v_period,
                        )
                    )

                if v_route is not None:
                    exp_result = exp_result and (
                        self._compare(
                            op="IN",
                            value1=[prescription_drug.route],
                            value2=v_route,
                        )
                    )

                if exp_result:
                    found = True
                    break

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

            filtered_list.append(item)

        return filtered_list

    def _is_safe_logical_expression(self, expr: str) -> bool:
        """Validates if the expression contains only safe logical operators and values"""

        return len(expr) < 500 and bool(re.fullmatch(SAFE_LOGICAL_EXPR_REGEX, expr))
