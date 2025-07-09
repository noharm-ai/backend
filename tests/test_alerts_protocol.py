"""Test: module for protocol alerts"""

from datetime import date, datetime, timedelta

import pytest

from models.prescription import Prescription, Patient
from tests.utils import utils_test_prescription
from utils.alert_protocol import AlertProtocol


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
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=2,
            dose=20,
            drug_name="Drug B",
            drug_class="J2",
            route="IV",
            frequency=1,
            period=1,
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
    exams = {
        "age": 50,
        "weight": 80,
        "ckd21": {
            "value": 3.2,
            "date": (date.today() - timedelta(days=3)).isoformat(),
        },
    }

    patient = Patient()
    patient.admissionDate = datetime.now() - timedelta(days=2)

    alert_protocol = AlertProtocol(
        drugs=drug_list, exams=exams, prescription=prescription, patient=patient
    )
    results = alert_protocol.get_protocol_alerts(protocol=protocol)

    if has_result:
        assert results is not None
    else:
        assert results is None


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

    alert_protocol = AlertProtocol(
        drugs=drug_list, exams={}, prescription=prescription, patient=patient
    )
    result = alert_protocol.get_protocol_alerts(protocol=protocol)

    assert result is not None
    assert len(result.get("variableMessages")) == 1
    assert (
        result.get("variableMessages")[0]
        == "Prescrição deve conter um medicamento ANTIEMETICO"
    )
