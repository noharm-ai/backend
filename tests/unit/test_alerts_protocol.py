"""Test: module for protocol alerts"""

from datetime import date, datetime, timedelta

import pytest

from models.prescription import Patient, Prescription
from tests.utils import utils_test_prescription
from utils.alert_protocol import AlertProtocol, ProtocolExtraInfo


@pytest.mark.parametrize(
    "protocol, has_result",
    [
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "substance",
                        "operator": "IN",
                        "value": ["111111"],
                    },
                    {
                        "name": "v2",
                        "field": "substance",
                        "operator": "IN",
                        "value": ["211111"],
                    },
                    {
                        "name": "v3",
                        "field": "substance",
                        "operator": "IN",
                        "value": ["311111"],
                    },
                ],
                "trigger": "{{v1}} and {{v2}} and {{v3}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "substance",
                        "operator": "IN",
                        "value": ["111111"],
                    },
                    {
                        "name": "v2",
                        "field": "substance",
                        "operator": "IN",
                        "value": ["211111"],
                    },
                    {
                        "name": "v3",
                        "field": "substance",
                        "operator": "IN",
                        "value": ["311111"],
                    },
                    {
                        "name": "v4",
                        "field": "substance",
                        "operator": "IN",
                        "value": ["411111"],
                    },
                ],
                "trigger": "{{v1}} and {{v2}} and {{v3}} and {{v4}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "substance",
                        "operator": "IN",
                        "value": ["111111", "NOT_EXISTENT"],
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "substance",
                        "operator": "NOTIN",
                        "value": ["NOTEXISTENT1"],
                    },
                    {
                        "name": "v2",
                        "field": "substance",
                        "operator": "IN",
                        "value": ["211111"],
                    },
                ],
                "trigger": "{{v1}} and {{v2}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "substance",
                        "operator": "NOTIN",
                        "value": ["111111"],
                    },
                    {
                        "name": "v2",
                        "field": "substance",
                        "operator": "NOTIN",
                        "value": ["211111"],
                    },
                ],
                "trigger": "{{v1}} and {{v2}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "substance",
                        "operator": "IN",
                        "value": ["111111"],
                    },
                    {
                        "name": "v2",
                        "field": "substance",
                        "operator": "IN",
                        "value": ["NOT_EXISTENT"],
                    },
                ],
                "trigger": "{{v1}} and {{v2}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "idDrug",
                        "operator": "IN",
                        "value": [1],
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "idDrug",
                        "operator": "IN",
                        "value": [99],
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "class",
                        "operator": "IN",
                        "value": ["J1"],
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "class",
                        "operator": "IN",
                        "value": ["J1"],
                    },
                    {
                        "name": "v2",
                        "field": "class",
                        "operator": "IN",
                        "value": ["SS"],
                    },
                ],
                "trigger": "{{v1}} and {{v2}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "substance",
                        "operator": "IN",
                        "value": ["111111"],
                    },
                    {
                        "name": "v2",
                        "field": "class",
                        "operator": "IN",
                        "value": ["J2"],
                    },
                ],
                "trigger": "{{v1}} and {{v2}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "class",
                        "operator": "NOTIN",
                        "value": ["J2"],
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "exam",
                        "examType": "ckd21",
                        "operator": ">",
                        "value": 2,
                    }
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "exam",
                        "examType": "ckd21",
                        "operator": "<",
                        "value": 5,
                    }
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "exam",
                        "examType": "ckd21",
                        "operator": "<=",
                        "value": 3.2,
                    }
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "exam",
                        "examType": "ckd21",
                        "examPeriod": 2,
                        "operator": "<=",
                        "value": 3.2,
                    }
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "exam",
                        "examType": "ckd21",
                        "examPeriod": 4,
                        "operator": "<=",
                        "value": 3.2,
                    }
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "exam",
                        "examType": "notexistent",
                        "operator": "<",
                        "value": 5,
                    }
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "age",
                        "operator": ">",
                        "value": 60,
                    }
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "age",
                        "operator": "<=",
                        "value": 60,
                    }
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "weight",
                        "operator": ">",
                        "value": 75,
                    }
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        # imc: weight 80kg / (170cm)^2 = 27.68
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "imc",
                        "operator": ">",
                        "value": 25,
                    }
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "imc",
                        "operator": ">=",
                        "value": 30,
                    }
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "idDrug",
                        "operator": "IN",
                        "value": [1],
                    },
                    {
                        "name": "v2",
                        "field": "route",
                        "operator": "IN",
                        "value": ["ORAL"],
                    },
                    {
                        "name": "v3",
                        "field": "substance",
                        "operator": "IN",
                        "value": ["DIETA"],
                    },
                ],
                "trigger": "{{v1}} and ({{v2}} or {{v3}})",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "idDepartment",
                        "operator": "IN",
                        "value": [1],
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "idDepartment",
                        "operator": "IN",
                        "value": [100],
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "idSegment",
                        "operator": "IN",
                        "value": [1],
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "idSegment",
                        "operator": "IN",
                        "value": [2],
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "admissionTime",
                        "operator": ">=",
                        "value": 48,
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "admissionTime",
                        "operator": ">=",
                        "value": 50,
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "stConcilia",
                        "operator": "=",
                        "value": 1,
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "stConcilia",
                        "operator": "=",
                        "value": 0,
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "combination",
                        "substance": ["111111"],
                        "dose": 5,
                        "doseOperator": "<",
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "combination",
                        "substance": ["111111"],
                        "dose": 5,
                        "doseOperator": ">",
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "combination",
                        "substance": ["111111"],
                        "dose": 5,
                        "doseOperator": ">",
                        "frequencyday": 2,
                        "frequencydayOperator": "=",
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "combination",
                        "substance": ["111111"],
                        "dose": 5,
                        "doseOperator": ">",
                        "frequencyday": 2,
                        "frequencydayOperator": "=",
                        "route": ["IV", "ORAL"],
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "combination",
                        "substance": ["111111"],
                        "drug": ["1"],
                        "class": ["J1"],
                        "dose": 5,
                        "doseOperator": ">",
                        "frequencyday": 2,
                        "frequencydayOperator": "=",
                        "route": ["IV", "ORAL"],
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "combination",
                        "observation": "Take with food",
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "combination",
                        "observation": "other observation",
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "combination",
                        "substance": ["111111"],
                        "drug": ["1"],
                        "class": ["J1"],
                        "dose": 5,
                        "doseOperator": ">",
                        "frequencyday": 2,
                        "frequencydayOperator": "=",
                        "route": ["IV", "ORAL"],
                        "period": 2,
                        "periodOperator": ">",
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "combination",
                        "substance": ["111111"],
                        "intravenous": True,
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "combination",
                        "substance": ["111111"],
                        "intravenous": False,
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "combination",
                        "substance": ["211111"],
                        "feedingTube": True,
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "combination",
                        "substance": ["211111"],
                        "feedingTube": False,
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "combination",
                        "substance": ["111111"],
                        "intravenous": True,
                        "defaultMeasureUnit": "mg",
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "combination",
                        "substance": ["111111"],
                        "intravenous": True,
                        "defaultMeasureUnit": "ml",
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "cn_stats",
                        "statsType": "diliexc",
                        "operator": "=",
                        "value": 0,
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "cn_stats",
                        "statsType": "diliexc",
                        "operator": ">",
                        "value": 0,
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "idIcd",
                        "operator": "IN",
                        "value": ["a00"],
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "idIcd",
                        "operator": "IN",
                        "value": ["a01", "a02"],
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "dischargeReason",
                        "value": "melhorado",
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "dischargeReason",
                        "value": "transferido",
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "segmentType",
                        "operator": "IN",
                        "value": ["1"],
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "segmentType",
                        "operator": "IN",
                        "value": ["2"],
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "insurance",
                        "operator": "CONTAINS",
                        "value": "AB",
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "insurance",
                        "operator": "CONTAINS",
                        "value": "ZXY",
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "tags",
                        "operator": "IN",
                        "value": ["oncologia"],
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "tags",
                        "operator": "IN",
                        "value": ["DIALISE", "TRANSPLANTE"],
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "tags",
                        "operator": "NOTIN",
                        "value": ["DIALISE"],
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "tags",
                        "operator": "NOTIN",
                        "value": ["PALIATIVO"],
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "exam_ref",
                        "examRefType": "ckd21_nh",
                        "operator": ">",
                        "value": 4,
                    }
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "exam_ref",
                        "examRefType": "ckd21_nh",
                        "operator": "<",
                        "value": 4,
                    }
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "exam_ref",
                        "examRefType": "ckd21_nh",
                        "examRefPeriod": 4,
                        "operator": "<",
                        "value": 4,
                    }
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "exam_ref",
                        "examRefType": "ckd21_nh",
                        "examRefPeriod": 2,  # not ok
                        "operator": "<",
                        "value": 4,  # ok
                    }
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "combination",
                        "substance": ["111111"],
                        "drugAttribute": ["antimicro", "controlled"],
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "combination",
                        "substance": ["111111"],
                        "drugAttribute": ["elderly"],
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            False,
        ),
        # absence of an exam: "> 0" is true whenever a result exists, so the
        # negated trigger is what detects a patient without the exam
        (
            {
                "variables": [
                    {"name": "tem", "field": "exam", "examType": "ckd21",
                     "operator": ">", "value": 0},
                ],
                "trigger": "{{tem}}",
                "result": {"message": "result"},
            },
            True,
        ),
        (
            {
                "variables": [
                    {"name": "tem", "field": "exam", "examType": "ckd21",
                     "operator": ">", "value": 0},
                ],
                "trigger": "not {{tem}}",
                "result": {"message": "result"},
            },
            False,
        ),
        (
            {
                "variables": [
                    {"name": "tem", "field": "exam", "examType": "hemograma",
                     "operator": ">", "value": 0},
                ],
                "trigger": "not {{tem}}",
                "result": {"message": "result"},
            },
            True,
        ),
        # combined with another condition
        (
            {
                "variables": [
                    {"name": "idoso", "field": "age", "operator": ">", "value": 40},
                    {"name": "tem", "field": "exam", "examType": "hemograma",
                     "operator": ">", "value": 0},
                ],
                "trigger": "{{idoso}} and not {{tem}}",
                "result": {"message": "result"},
            },
            True,
        ),
        # the sentinel the model reaches for instead: never matches
        (
            {
                "variables": [
                    {"name": "sem", "field": "exam", "examType": "ckd21",
                     "operator": "=", "value": -999},
                ],
                "trigger": "{{sem}}",
                "result": {"message": "result"},
            },
            False,
        ),
    ],
)
def test_trigger(protocol, has_result):
    """Protocols: test trigger conditions"""

    drug_list = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=1,
            dose=10,
            drug_name="Drug A",
            drug_class="J1",
            route="IV",
            frequency=2,
            period=5,
            notes="Take with food",
            intravenous=True,
            measure_unit_nh="mg",
            antimicro=True,
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=2,
            dose=20,
            drug_name="Drug B",
            drug_class="J2",
            route="IV",
            frequency=1,
            period=1,
            tube=True,
            measure_unit_nh="ml",
            controlled=True,
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=3,
            dose=20,
            drug_name="Drug C",
            drug_class="J3",
            route="ORAL",
            frequency=3,
            period=5,
        ),
    ]

    prescription = Prescription()
    prescription.idDepartment = 100
    prescription.idSegment = 1
    prescription.insurance = "ABCD"
    exams = {
        "age": 50,
        "weight": 80,
        "height": 170,
        "ckd21": {
            "value": 3.2,
            "date": (date.today() - timedelta(days=3)).isoformat(),
            "tp_exam_ref": "ckd21_nh",
        },
    }
    cn_stats = {"diliexc": 1, "complication": 0}

    patient = Patient()
    patient.admissionDate = datetime.now() - timedelta(days=2)
    patient.st_conciliation = 1
    patient.id_icd = "A00"
    patient.dischargeReason = "Alta melhorado"
    patient.tags = ["ONCOLOGIA", "PALIATIVO"]

    protocol_extra_info = ProtocolExtraInfo()
    protocol_extra_info.segment_type = 1

    alert_protocol = AlertProtocol(
        drugs=drug_list,
        exams=exams,
        prescription=prescription,
        patient=patient,
        cn_stats=cn_stats,
        protocol_extra_info=protocol_extra_info,
    )
    results = alert_protocol.get_protocol_alerts(protocol=protocol)

    if has_result:
        assert results is not None
    else:
        assert results is None


def _tags_protocol(operator: str, value: list) -> dict:
    """Protocol with a single patient tags variable"""

    return {
        "variables": [
            {"name": "v1", "field": "tags", "operator": operator, "value": value}
        ],
        "trigger": "{{v1}}",
        "result": {"message": "result"},
    }


def _tags_alert_protocol(patient: Patient) -> AlertProtocol:
    """AlertProtocol with no drugs, bound to the given patient"""

    return AlertProtocol(
        drugs=[],
        exams={},
        prescription=Prescription(),
        patient=patient,
        cn_stats={},
    )


@pytest.mark.parametrize(
    "tags, operator, has_result",
    [
        # a patient without tags never matches IN and always matches NOTIN
        (None, "IN", False),
        (None, "NOTIN", True),
        ([], "IN", False),
        ([], "NOTIN", True),
        # comparison ignores case on both sides
        (["Oncologia"], "IN", True),
        (["Oncologia"], "NOTIN", False),
    ],
)
def test_tags_variable(tags, operator, has_result):
    """Protocols: patient tags variable against patients with and without tags"""

    patient = Patient()
    patient.tags = tags

    alert_protocol = _tags_alert_protocol(patient=patient)
    results = alert_protocol.get_protocol_alerts(
        protocol=_tags_protocol(operator=operator, value=["oncologia"])
    )

    assert (results is not None) == has_result


def test_tags_variable_unsupported_operator():
    """Protocols: patient tags variable only accepts list operators"""

    patient = Patient()
    patient.tags = ["ONCOLOGIA"]

    alert_protocol = _tags_alert_protocol(patient=patient)
    trace = alert_protocol.evaluate_with_trace(
        protocol=_tags_protocol(operator="=", value=["ONCOLOGIA"])
    )

    assert trace["activated"] is False
    assert trace["variables"][0].reason == "OPERATOR_NOT_SUPPORTED"


def test_tags_variable_trace():
    """Protocols: patient tags variable trace reports the matched tags"""

    patient = Patient()
    patient.tags = ["ONCOLOGIA", "PALIATIVO"]

    alert_protocol = _tags_alert_protocol(patient=patient)
    trace = alert_protocol.evaluate_with_trace(
        protocol=_tags_protocol(operator="IN", value=["paliativo", "DIALISE"])
    )

    assert trace["activated"] is True
    variable = trace["variables"][0]
    assert variable.result is True
    assert variable.reason == "COMPARED"
    assert variable.actual_value == ["ONCOLOGIA", "PALIATIVO"]
    assert variable.details["matched"] == ["PALIATIVO"]


def _admission_number_protocol(operator: str, value: list) -> dict:
    """Protocol with a single admission number variable"""

    return {
        "variables": [
            {
                "name": "v1",
                "field": "admissionNumber",
                "operator": operator,
                "value": value,
            }
        ],
        "trigger": "{{v1}}",
        "result": {"message": "result"},
    }


@pytest.mark.parametrize(
    "admission_number, value, operator, has_result",
    [
        # exact match, typed as string or number
        (123456, ["123456"], "IN", True),
        (123456, [123456], "IN", True),
        (123456, ["123456"], "NOTIN", False),
        # stray whitespace typed by the user is ignored
        (123456, [" 123456 "], "IN", True),
        # not in the list
        (123456, ["654321", "111"], "IN", False),
        (123456, ["654321", "111"], "NOTIN", True),
        # empty list never matches IN and always matches NOTIN
        (123456, [], "IN", False),
        (123456, [], "NOTIN", True),
        (123456, None, "IN", False),
        # patient without admission number never activates the protocol
        (None, ["123456"], "IN", False),
        (None, ["123456"], "NOTIN", False),
    ],
)
def test_admission_number_variable(admission_number, value, operator, has_result):
    """Protocols: admission number variable tested against Patient.admissionNumber"""

    patient = Patient()
    patient.admissionNumber = admission_number

    alert_protocol = _tags_alert_protocol(patient=patient)
    results = alert_protocol.get_protocol_alerts(
        protocol=_admission_number_protocol(operator=operator, value=value)
    )

    assert (results is not None) == has_result


def test_admission_number_variable_unsupported_operator():
    """Protocols: admission number variable only accepts list operators"""

    patient = Patient()
    patient.admissionNumber = 123456

    alert_protocol = _tags_alert_protocol(patient=patient)
    trace = alert_protocol.evaluate_with_trace(
        protocol=_admission_number_protocol(operator="=", value=["123456"])
    )

    assert trace["activated"] is False
    assert trace["variables"][0].reason == "OPERATOR_NOT_SUPPORTED"


def test_admission_number_variable_trace():
    """Protocols: admission number variable trace reports the matched number"""

    patient = Patient()
    patient.admissionNumber = 123456

    alert_protocol = _tags_alert_protocol(patient=patient)
    trace = alert_protocol.evaluate_with_trace(
        protocol=_admission_number_protocol(operator="IN", value=["999", "123456"])
    )

    assert trace["activated"] is True
    variable = trace["variables"][0]
    assert variable.result is True
    assert variable.reason == "COMPARED"
    assert variable.actual_value == ["123456"]
    assert variable.details["matched"] == ["123456"]


@pytest.mark.parametrize(
    "protocol, related_items",
    [
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "combination",
                        "class": ["J1"],
                        "dose": 5,
                        "doseOperator": ">",
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            [1],
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "combination",
                        "class": ["J1", "J2"],
                        "dose": 5,
                        "doseOperator": ">",
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            [1, 2],
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "combination",
                        "class": ["J1"],
                        "dose": 5,
                        "doseOperator": ">",
                    },
                    {
                        "name": "v2",
                        "field": "combination",
                        "class": ["J2"],
                        "dose": 5,
                        "doseOperator": ">",
                    },
                ],
                "trigger": "{{v1}} and {{v2}}",
                "result": {"message": "result"},
            },
            [1, 2],
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "combination",
                        "class": ["J1"],
                        "dose": 5,
                        "doseOperator": ">",
                    },
                    {
                        "name": "v2",
                        "field": "combination",
                        "class": ["J2"],
                        "dose": 30,
                        "doseOperator": ">",
                    },
                ],
                "trigger": "{{v1}} and {{v2}}",
                "result": {"message": "result"},
            },
            None,
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "combination",
                        "class": ["J1"],
                        "dose": 5,
                        "doseOperator": ">",
                    },
                    {
                        "name": "v2",
                        "field": "combination",
                        "class": ["J2"],
                        "dose": 30,
                        "doseOperator": ">",
                    },
                ],
                "trigger": "{{v1}} and not {{v2}}",
                "result": {"message": "result"},
            },
            [1],
        ),
        (
            {
                "variables": [
                    {
                        "name": "v1",
                        "field": "combination",
                        "class": ["J3"],
                        "dose": 10,
                        "doseOperator": ">",
                    },
                ],
                "trigger": "{{v1}}",
                "result": {"message": "result"},
            },
            [3, 4],
        ),
    ],
)
def test_item_protocol(protocol, related_items):
    """Protocols: test protocols applied to prescription items"""

    drug_list = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=1,
            dose=10,
            drug_name="Drug A",
            drug_class="J1",
            route="IV",
            frequency=2,
            period=5,
            notes="Take with food",
            measure_unit_nh="mg",
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=2,
            dose=20,
            drug_name="Drug B",
            drug_class="J2",
            route="IV",
            frequency=1,
            period=1,
            measure_unit_nh="ml",
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=3,
            dose=20,
            drug_name="Drug C",
            drug_class="J3",
            route="ORAL",
            frequency=3,
            period=5,
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=4,
            dose=20,
            drug_name="Drug C",
            drug_class="J3",
            route="ORAL",
            frequency=3,
            period=5,
        ),
    ]

    prescription = Prescription()
    prescription.idDepartment = 100
    prescription.idSegment = 1
    exams = {
        "age": 50,
        "weight": 80,
        "ckd21": {
            "value": 3.2,
            "date": (date.today() - timedelta(days=3)).isoformat(),
        },
    }
    cn_stats = {"diliexc": 1, "complication": 0}

    patient = Patient()
    patient.admissionDate = datetime.now() - timedelta(days=2)
    patient.st_conciliation = 1
    patient.id_icd = "A00"
    patient.dischargeReason = "Alta melhorado"

    alert_protocol = AlertProtocol(
        drugs=drug_list,
        exams=exams,
        prescription=prescription,
        patient=patient,
        cn_stats=cn_stats,
    )
    result = alert_protocol.get_protocol_alerts(protocol=protocol)

    if related_items is not None:
        assert result is not None

        result_related_items = result.get("related_items")
        assert len(result_related_items) == len(related_items)
        assert set(result_related_items) == set(related_items)

    else:
        assert result is None


def test_folfox():
    """Protocols: test folfox protocol"""

    drug_list = [
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
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=3,
            dose=20,
            drug_name="ÁCIDO FOLÍNICO",
            drug_class="Q1",
            sctid="ÁCIDO FOLÍNICO",
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=4,
            dose=20,
            drug_name="DEXAMETASONA",
            drug_class="Q1",
            sctid="DEXAMETASONA",
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=5,
            dose=20,
            drug_name="DIFENIDRAMINA",
            drug_class="Q1",
            sctid="DIFENIDRAMINA",
        ),
        # utils_test_prescription.get_prescription_drug_mock_row(
        #     id_prescription_drug=6,
        #     dose=20,
        #     drug_name="ANTIEMETICO",
        #     drug_class="ANTIEMETICO",
        #     sctid="ANTIEMETICO",
        # ),
    ]

    protocol = {
        "variables": [
            {
                "name": "possui_fluorouracil",
                "field": "substance",
                "operator": "IN",
                "value": ["FLUOROURACIL"],
            },
            {
                "name": "possui_oxaliplatina",
                "field": "substance",
                "operator": "IN",
                "value": ["OXALIPLATINA"],
            },
            {
                "name": "possui_acido_folico",
                "field": "substance",
                "operator": "IN",
                "value": ["ÁCIDO FOLÍNICO"],
            },
            {
                "name": "naopossui_dexametasona",
                "field": "substance",
                "operator": "NOTIN",
                "value": ["DEXAMETASONA"],
                "message": {
                    "if": True,
                    "then": "Prescrição deve conter DEXAMETASONA",
                },
            },
            {
                "name": "naopossui_difenidramina",
                "field": "substance",
                "operator": "NOTIN",
                "value": ["DIFENIDRAMINA"],
                "message": {
                    "if": True,
                    "then": "Prescrição deve conter DIFENIDRAMINA",
                },
            },
            {
                "name": "naopossui_antiemetico",
                "field": "class",
                "operator": "NOTIN",
                "value": ["ANTIEMETICO"],
                "message": {
                    "if": True,
                    "then": "Prescrição deve conter um medicamento ANTIEMETICO",
                },
            },
        ],
        "trigger": "{{possui_fluorouracil}} and {{possui_oxaliplatina}} and {{possui_acido_folico}} and ({{naopossui_difenidramina}} or {{naopossui_dexametasona}} or {{naopossui_antiemetico}})",
        "result": {
            "type": "SHOW_MESSAGE",
            "level": "high",
            "message": "De acordo com o protocolo FOLFOX:",
        },
    }

    prescription = Prescription()
    prescription.idDepartment = 100

    patient = Patient()

    cn_stats = {"diliexc": 1, "complication": 0}

    alert_protocol = AlertProtocol(
        drugs=drug_list,
        exams={},
        prescription=prescription,
        patient=patient,
        cn_stats=cn_stats,
    )
    result = alert_protocol.get_protocol_alerts(protocol=protocol)

    assert result is not None
    assert len(result.get("variableMessages")) == 1
    assert (
        result.get("variableMessages")[0]
        == "Prescrição deve conter um medicamento ANTIEMETICO"
    )


def _culture_release_protocol(operator: str, value) -> dict:
    """Protocol with a single culture release time variable"""

    return {
        "variables": [
            {
                "name": "v1",
                "field": "cultureReleaseTime",
                "operator": operator,
                "value": value,
            }
        ],
        "trigger": "{{v1}}",
        "result": {"message": "result"},
    }


def _culture(result, hours_ago: float, drug: str = "Drug A") -> dict:
    """One culture of a drug, released the given number of hours ago.

    A pending collection is one with no result (culture_service): it may still
    carry a release date of its own, which is exactly what must not be read as
    the age of the newest antibiogram.
    """

    return {
        "drug": drug,
        "items": [
            {
                "result": result,
                "releaseDate": (
                    datetime.now() - timedelta(hours=hours_ago)
                ).isoformat(),
            }
        ],
    }


def _culture_alert_protocol(cultures) -> AlertProtocol:
    """AlertProtocol with no drugs, bound to the given cultures"""

    return AlertProtocol(
        drugs=[],
        exams={},
        prescription=Prescription(),
        patient=Patient(),
        cn_stats={},
        cultures=cultures,
    )


@pytest.mark.parametrize(
    "hours_ago, operator, value, has_result",
    [
        # released 6 hours ago: recent under "<", not old under ">"
        (6, "<", 48, True),
        (6, ">", 48, False),
        # released 5 days ago: the other way around
        (120, "<", 48, False),
        (120, ">", 48, True),
        # the comparison keeps the time of day, so a threshold between two
        # whole days still decides correctly
        (30, ">", 24, True),
        (30, "<", 24, False),
        # the configured value may arrive as text from the protocol form
        (6, "<", "48", True),
    ],
)
def test_culture_release_time_variable(hours_ago, operator, value, has_result):
    """Protocols: hours elapsed since the newest released antibiogram"""

    alert_protocol = _culture_alert_protocol(
        cultures=[_culture(result="Resistente", hours_ago=hours_ago)]
    )
    results = alert_protocol.get_protocol_alerts(
        protocol=_culture_release_protocol(operator=operator, value=value)
    )

    assert (results is not None) == has_result


@pytest.mark.parametrize("operator", ["<", ">", "=", "!="])
def test_culture_release_time_without_cultures(operator):
    """Protocols: a patient with no culture is false under every operator.

    There is no value that means "no culture": a protocol that needs the
    absence of one declares the variable positively and negates it in the
    trigger, like the exam fields do.
    """

    alert_protocol = _culture_alert_protocol(cultures=None)
    trace = alert_protocol.evaluate_with_trace(
        protocol=_culture_release_protocol(operator=operator, value=48)
    )

    assert trace["activated"] is False
    assert trace["variables"][0].reason == "NO_CULTURE_RELEASE"


def test_culture_release_time_ignores_pending_collection():
    """Protocols: only a released antibiogram dates the newest culture.

    A pending collection carries a release date but no result, and the culture
    card states the newest RELEASED date to the pharmacist
    (features/culture/CultureCardFooter). Reading the pending one here would
    make the protocol disagree with the date on the same screen.
    """

    cultures = [
        # the newest date belongs to a collection still waiting for its result
        _culture(result=None, hours_ago=1, drug="Drug A"),
        _culture(result="Sensível", hours_ago=72, drug="Drug B"),
    ]

    alert_protocol = _culture_alert_protocol(cultures=cultures)

    # 72h old, not 1h old
    assert (
        alert_protocol.get_protocol_alerts(
            protocol=_culture_release_protocol(operator=">", value=48)
        )
        is not None
    )
    assert (
        alert_protocol.get_protocol_alerts(
            protocol=_culture_release_protocol(operator="<", value=48)
        )
        is None
    )


def test_culture_release_time_only_pending_collections():
    """Protocols: cultures that are all pending count as no released culture"""

    alert_protocol = _culture_alert_protocol(
        cultures=[_culture(result=None, hours_ago=1)]
    )
    trace = alert_protocol.evaluate_with_trace(
        protocol=_culture_release_protocol(operator="<", value=48)
    )

    assert trace["activated"] is False
    assert trace["variables"][0].reason == "NO_CULTURE_RELEASE"


def test_culture_release_time_uses_the_newest_release():
    """Protocols: several released antibiograms are dated by the newest one"""

    alert_protocol = _culture_alert_protocol(
        cultures=[
            _culture(result="Resistente", hours_ago=200, drug="Drug A"),
            _culture(result="Sensível", hours_ago=10, drug="Drug B"),
        ]
    )
    trace = alert_protocol.evaluate_with_trace(
        protocol=_culture_release_protocol(operator="<", value=48)
    )

    assert trace["activated"] is True
    assert trace["variables"][0].reason == "COMPARED"


def test_culture_release_time_invalid_date():
    """Protocols: an unreadable release date is a traced miss, not a crash"""

    cultures = [
        {
            "drug": "Drug A",
            "items": [{"result": "Resistente", "releaseDate": "not-a-date"}],
        }
    ]

    alert_protocol = _culture_alert_protocol(cultures=cultures)
    trace = alert_protocol.evaluate_with_trace(
        protocol=_culture_release_protocol(operator="<", value=48)
    )

    assert trace["activated"] is False
    assert trace["variables"][0].reason == "CULTURE_DATE_INVALID"


def test_culture_release_time_non_numeric_value():
    """Protocols: a non-numeric threshold is reported as a configuration miss"""

    alert_protocol = _culture_alert_protocol(
        cultures=[_culture(result="Resistente", hours_ago=6)]
    )
    trace = alert_protocol.evaluate_with_trace(
        protocol=_culture_release_protocol(operator="<", value="quarenta e oito")
    )

    assert trace["activated"] is False
    assert trace["variables"][0].reason == "VALUE_NOT_NUMERIC"
