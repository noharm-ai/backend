"""AlertProtocol class: test protocol rules against prescription data"""

import re

from models.enums import DrugTypeEnum
from models.main import Substance
from models.prescription import PrescriptionDrug

SAFE_LOGICAL_EXPR_REGEX = r"^\s*(?:True|False|\(|\)|and|or|not|\s+)+\s*$"


class AlertProtocol:
    """AlertProtocol class: test protocol rules against prescription data"""

    drugs = None
    filtered_drugs = None
    substance_list = []
    class_list = []
    id_drug_list = []
    route_list = []
    exams = None
    protocol_variables = {}
    protocol_msgs = []

    def __init__(self, drugs: dict, exams: dict):
        self.drugs = drugs
        self.filtered_drugs = self._filter_drug_list()
        self.exams = exams

        # fill lists
        for d in self.filtered_drugs:
            prescription_drug: PrescriptionDrug = d[0]
            substance: Substance = d[11]

            if prescription_drug.idDrug:
                self.id_drug_list.append(prescription_drug.idDrug)

            if prescription_drug.route:
                self.route_list.append(prescription_drug.route)

            if substance:
                self.substance_list.append(substance.id)

            if substance and substance.idclass:
                self.class_list.append(substance.idclass)

    def get_protocol_alerts(self, protocol: dict):
        """get configured protocol alerts"""

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
            result["protocolMessages"] = self.protocol_msgs
            return result

        return None

    def _fill_variable(self, variable: dict):
        field = variable.get("field", None)
        operator = variable.get("operator")
        value = variable.get("value")

        if field == "substance":
            return self._compare(op=operator, value1=self.substance_list, value2=value)

        if field == "class":
            return self._compare(op=operator, value1=self.class_list, value2=value)

        if field == "idDrug":
            return self._compare(op=operator, value1=self.id_drug_list, value2=value)

        if field == "route":
            return self._compare(op=operator, value1=self.route_list, value2=value)

        if field == "exam":
            exam_type = variable.get("examType")
            if exam_type not in self.exams:
                return False

            return self._compare(
                op=operator, value1=self.exams[exam_type]["value"], value2=value
            )

        if field == "age":
            age = self.exams.get("age", None)
            if not age:
                return False

            return self._compare(op=operator, value1=age, value2=value)

        if field == "weight":
            weight = self.exams.get("weight", None)
            if not weight:
                return False

            return self._compare(op=operator, value1=weight, value2=value)

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
            DrugTypeEnum.DIET,
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
