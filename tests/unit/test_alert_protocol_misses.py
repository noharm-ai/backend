"""Test: why a protocol variable does *not* match (AlertProtocol miss paths)

A protocol variable that cannot be evaluated never raises: it answers False and
records *why* in the trace, through ``_trace_miss``. Those reasons are what the
pharmacist reads when a protocol they expected to fire stayed quiet, so each one
has to point at the right cause — "this exam is 10 days old" and "this patient
has no weight registered" must not collapse into a single silent False.

``tests/unit/test_alert_protocol_trace.py`` covers the happy paths and the two
exam reasons; this file covers the remaining data-missing exits of
``_fill_variable`` (one per field), the guard rails around them
(``_filter_drug_list``, ``_is_safe_logical_expression``, ``_compare`` and
``_get_drug_attribute_keys``) and the exam-by-reference index built in the
constructor.

Everything here is pure in-memory evaluation: the mock rows come from
``tests.utils.utils_test_prescription`` and no database is touched.
"""

from datetime import date, datetime, timedelta

import pytest

from models.main import DrugAttributes
from models.prescription import Patient, Prescription
from tests.utils import utils_test_prescription
from utils.alert_protocol import AlertProtocol, ProtocolExtraInfo
from utils.alert_protocol_trace import TraceReasonEnum

RESULT = {"type": "SHOW_MESSAGE", "level": "high", "message": "test"}


def _get_alert_protocol(
    drug_list=None,
    exams=None,
    cn_stats=None,
    patient=None,
    prescription=None,
    protocol_extra_info=None,
):
    """Builds an AlertProtocol instance with minimal mock data"""

    if prescription is None:
        prescription = Prescription()
        prescription.idDepartment = 100

    if patient is None:
        patient = Patient()

    return AlertProtocol(
        drugs=drug_list if drug_list is not None else [],
        exams=exams if exams is not None else {},
        prescription=prescription,
        patient=patient,
        cn_stats=cn_stats if cn_stats is not None else {},
        protocol_extra_info=protocol_extra_info,
    )


def _single_variable_protocol(variable: dict):
    """Protocol with one variable named ``v``, activated when it is true"""

    return {
        "variables": [{"name": "v", **variable}],
        "trigger": "{{v}}",
        "result": RESULT.copy(),
    }


def _evaluate(alert_protocol: AlertProtocol, variable: dict):
    """Evaluates a one-variable protocol and returns its single VariableTrace"""

    trace = alert_protocol.evaluate_with_trace(
        protocol=_single_variable_protocol(variable)
    )

    return trace["variables"][0]


# ---------------------------------------------------------------------------
# exams_by_ref: the index the exam_ref field reads
# ---------------------------------------------------------------------------


def test_exam_ref_index_keeps_the_most_recent_exam_of_a_reference():
    """exams_by_ref: two exams sharing a reference keep the newer one"""

    exams = {
        "creat_old": {
            "value": 1.0,
            "date": "2024-01-01T10:00:00",
            "tp_exam_ref": "creatinina",
        },
        "creat_new": {
            "value": 2.0,
            "date": "2024-06-01T10:00:00",
            "tp_exam_ref": "creatinina",
        },
    }

    alert_protocol = _get_alert_protocol(exams=exams)

    assert alert_protocol.exams_by_ref["creatinina"]["value"] == 2.0


def test_exam_ref_index_ignores_an_older_exam_of_the_same_reference():
    """exams_by_ref: an older exam does not replace the one already indexed"""

    exams = {
        "creat_new": {
            "value": 2.0,
            "date": "2024-06-01T10:00:00",
            "tp_exam_ref": "creatinina",
        },
        "creat_old": {
            "value": 1.0,
            "date": "2024-01-01T10:00:00",
            "tp_exam_ref": "creatinina",
        },
    }

    alert_protocol = _get_alert_protocol(exams=exams)

    assert alert_protocol.exams_by_ref["creatinina"]["value"] == 2.0


def test_exam_ref_index_replaces_an_entry_that_carries_no_date():
    """exams_by_ref: a dated exam wins over one indexed without a date"""

    exams = {
        "creat_undated": {
            "value": 1.0,
            "date": None,
            "tp_exam_ref": "creatinina",
        },
        "creat_dated": {
            "value": 2.0,
            "date": "2024-06-01T10:00:00",
            "tp_exam_ref": "creatinina",
        },
    }

    alert_protocol = _get_alert_protocol(exams=exams)

    assert alert_protocol.exams_by_ref["creatinina"]["value"] == 2.0


def test_exam_ref_index_skips_entries_without_a_reference():
    """exams_by_ref: exams with no tp_exam_ref are not indexed"""

    exams = {
        "tgo": {"value": 50, "date": "2024-06-01T10:00:00"},
        "empty": None,
        "not_a_dict": 42,
    }

    alert_protocol = _get_alert_protocol(exams=exams)

    assert alert_protocol.exams_by_ref == {}


# ---------------------------------------------------------------------------
# cn_stats
# ---------------------------------------------------------------------------


def test_cn_stats_missing_indicator_reports_stat_not_found():
    """cn_stats: an indicator the patient has no record of is STAT_NOT_FOUND"""

    variable = _evaluate(
        _get_alert_protocol(cn_stats={"dialysis": 1}),
        {"field": "cn_stats", "statsType": "sepsis", "operator": ">", "value": 0},
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.STAT_NOT_FOUND.value
    assert variable.details["statsType"] == "sepsis"


def test_cn_stats_null_indicator_reports_stat_not_found():
    """cn_stats: an indicator present but null is STAT_NOT_FOUND too"""

    variable = _evaluate(
        _get_alert_protocol(cn_stats={"sepsis": None}),
        {"field": "cn_stats", "statsType": "sepsis", "operator": ">", "value": 0},
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.STAT_NOT_FOUND.value


def test_cn_stats_non_numeric_threshold_reports_value_not_numeric():
    """cn_stats: a threshold that is not a number is VALUE_NOT_NUMERIC"""

    variable = _evaluate(
        _get_alert_protocol(cn_stats={"sepsis": 1}),
        {"field": "cn_stats", "statsType": "sepsis", "operator": ">", "value": "abc"},
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.VALUE_NOT_NUMERIC.value
    assert variable.details["statsType"] == "sepsis"


def test_cn_stats_compares_when_the_indicator_is_present():
    """cn_stats: a present numeric indicator is compared normally"""

    variable = _evaluate(
        _get_alert_protocol(cn_stats={"sepsis": 3}),
        {"field": "cn_stats", "statsType": "sepsis", "operator": ">", "value": 5},
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.COMPARED.value
    assert variable.actual_value == 3


# ---------------------------------------------------------------------------
# exam
# ---------------------------------------------------------------------------


def test_exam_without_a_value_reports_exam_value_missing():
    """exam: a result row carrying no value is EXAM_VALUE_MISSING"""

    exams = {"tgo": {"value": None, "date": date.today().isoformat()}}

    variable = _evaluate(
        _get_alert_protocol(exams=exams),
        {"field": "exam", "examType": "tgo", "operator": ">", "value": 40},
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.EXAM_VALUE_MISSING.value
    assert variable.details["examType"] == "tgo"


def test_exam_with_an_unparsable_date_reports_exam_date_invalid():
    """exam: an unreadable collection date is EXAM_DATE_INVALID, not expired"""

    exams = {"tgo": {"value": 50, "date": "not-a-date"}}

    variable = _evaluate(
        _get_alert_protocol(exams=exams),
        {
            "field": "exam",
            "examType": "tgo",
            "examPeriod": 3,
            "operator": ">",
            "value": 40,
        },
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.EXAM_DATE_INVALID.value
    assert variable.details["examType"] == "tgo"


def test_exam_within_the_period_is_compared():
    """exam: a result inside examPeriod is compared instead of expiring"""

    exams = {
        "tgo": {
            "value": 50,
            "date": (date.today() - timedelta(days=1)).isoformat(),
        }
    }

    variable = _evaluate(
        _get_alert_protocol(exams=exams),
        {
            "field": "exam",
            "examType": "tgo",
            "examPeriod": 3,
            "operator": "<",
            "value": 40,
        },
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.COMPARED.value
    assert variable.actual_value == 50


def test_exam_with_a_non_numeric_value_reports_value_not_numeric():
    """exam: a textual result cannot be compared and is VALUE_NOT_NUMERIC"""

    exams = {"tgo": {"value": "indetectável", "date": date.today().isoformat()}}

    variable = _evaluate(
        _get_alert_protocol(exams=exams),
        {"field": "exam", "examType": "tgo", "operator": ">", "value": 40},
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.VALUE_NOT_NUMERIC.value
    assert variable.details["examType"] == "tgo"


# ---------------------------------------------------------------------------
# exam_ref
# ---------------------------------------------------------------------------


def _exam_ref_variable(**extra):
    return {
        "field": "exam_ref",
        "examRefType": "creatinina",
        "operator": ">",
        "value": 1.0,
        **extra,
    }


def test_exam_ref_without_any_indexed_exam_reports_exam_not_found():
    """exam_ref: an empty reference index is EXAM_NOT_FOUND"""

    variable = _evaluate(_get_alert_protocol(), _exam_ref_variable())

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.EXAM_NOT_FOUND.value
    assert variable.details["examType"] == "creatinina"


def test_exam_ref_for_another_reference_reports_exam_not_found():
    """exam_ref: an index holding other references is EXAM_NOT_FOUND"""

    exams = {
        "tgo": {"value": 50, "date": date.today().isoformat(), "tp_exam_ref": "tgo_ref"}
    }

    variable = _evaluate(_get_alert_protocol(exams=exams), _exam_ref_variable())

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.EXAM_NOT_FOUND.value


def test_exam_ref_without_a_value_reports_exam_value_missing():
    """exam_ref: an indexed exam carrying no value is EXAM_VALUE_MISSING"""

    exams = {
        "creat": {
            "value": None,
            "date": date.today().isoformat(),
            "tp_exam_ref": "creatinina",
        }
    }

    variable = _evaluate(_get_alert_protocol(exams=exams), _exam_ref_variable())

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.EXAM_VALUE_MISSING.value


def test_exam_ref_older_than_the_period_reports_exam_expired():
    """exam_ref: a result older than examRefPeriod is EXAM_EXPIRED"""

    exams = {
        "creat": {
            "value": 2.0,
            "date": (date.today() - timedelta(days=10)).isoformat(),
            "tp_exam_ref": "creatinina",
        }
    }

    variable = _evaluate(
        _get_alert_protocol(exams=exams), _exam_ref_variable(examRefPeriod=3)
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.EXAM_EXPIRED.value
    assert variable.details["daysDiff"] == 10
    assert variable.details["examPeriod"] == 3


def test_exam_ref_with_an_unparsable_date_reports_exam_date_invalid():
    """exam_ref: an unreadable collection date is EXAM_DATE_INVALID"""

    exams = {
        "creat": {
            "value": 2.0,
            "date": "not-a-date",
            "tp_exam_ref": "creatinina",
        }
    }

    variable = _evaluate(
        _get_alert_protocol(exams=exams), _exam_ref_variable(examRefPeriod=3)
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.EXAM_DATE_INVALID.value


def test_exam_ref_with_a_non_numeric_value_reports_value_not_numeric():
    """exam_ref: a textual result is VALUE_NOT_NUMERIC"""

    exams = {
        "creat": {
            "value": "indetectável",
            "date": date.today().isoformat(),
            "tp_exam_ref": "creatinina",
        }
    }

    variable = _evaluate(_get_alert_protocol(exams=exams), _exam_ref_variable())

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.VALUE_NOT_NUMERIC.value


def test_exam_ref_compares_the_indexed_exam():
    """exam_ref: a usable indexed exam is compared and carries its date"""

    exam_date = date.today().isoformat()
    exams = {"creat": {"value": 2.0, "date": exam_date, "tp_exam_ref": "creatinina"}}

    trace = _get_alert_protocol(exams=exams).evaluate_with_trace(
        protocol=_single_variable_protocol(_exam_ref_variable())
    )

    variable = trace["variables"][0]

    assert trace["activated"] is True
    assert variable.result is True
    assert variable.reason == TraceReasonEnum.COMPARED.value
    assert variable.actual_value == 2.0
    assert variable.details["examDate"] == exam_date


# ---------------------------------------------------------------------------
# admissionTime
# ---------------------------------------------------------------------------


def test_admission_time_without_a_patient_reports_no_patient():
    """admissionTime: no patient record at all is NO_PATIENT"""

    alert_protocol = _get_alert_protocol()
    alert_protocol.patient = None

    variable = _evaluate(
        alert_protocol,
        {"field": "admissionTime", "operator": ">", "value": 24},
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.NO_PATIENT.value


def test_admission_time_without_an_admission_date_reports_no_admission_date():
    """admissionTime: a patient with no admission date is NO_ADMISSION_DATE"""

    variable = _evaluate(
        _get_alert_protocol(),
        {"field": "admissionTime", "operator": ">", "value": 24},
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.NO_ADMISSION_DATE.value


def test_admission_time_with_a_non_numeric_threshold_reports_value_not_numeric():
    """admissionTime: a threshold that is not a number is VALUE_NOT_NUMERIC"""

    patient = Patient()
    patient.admissionDate = datetime.now() - timedelta(days=2)

    variable = _evaluate(
        _get_alert_protocol(patient=patient),
        {"field": "admissionTime", "operator": ">", "value": "abc"},
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.VALUE_NOT_NUMERIC.value


def test_admission_time_compares_the_elapsed_hours():
    """admissionTime: an admitted patient is compared in hours"""

    patient = Patient()
    patient.admissionDate = datetime.now() - timedelta(hours=48)

    trace = _get_alert_protocol(patient=patient).evaluate_with_trace(
        protocol=_single_variable_protocol(
            {"field": "admissionTime", "operator": ">", "value": 24}
        )
    )

    variable = trace["variables"][0]

    assert trace["activated"] is True
    assert variable.reason == TraceReasonEnum.COMPARED.value
    assert variable.actual_value == pytest.approx(48, abs=1)


# ---------------------------------------------------------------------------
# stConcilia
# ---------------------------------------------------------------------------


def test_st_concilia_without_a_patient_reports_no_patient():
    """stConcilia: no patient record is NO_PATIENT"""

    alert_protocol = _get_alert_protocol()
    alert_protocol.patient = None

    variable = _evaluate(
        alert_protocol, {"field": "stConcilia", "operator": "=", "value": 1}
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.NO_PATIENT.value


def test_st_concilia_with_a_non_numeric_value_reports_value_not_numeric():
    """stConcilia: a non-numeric expected status is VALUE_NOT_NUMERIC"""

    variable = _evaluate(
        _get_alert_protocol(),
        {"field": "stConcilia", "operator": "=", "value": "abc"},
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.VALUE_NOT_NUMERIC.value


def test_st_concilia_defaults_to_zero_when_the_patient_has_none():
    """stConcilia: a patient without the status compares as 0"""

    variable = _evaluate(
        _get_alert_protocol(), {"field": "stConcilia", "operator": "=", "value": 0}
    )

    assert variable.result is True
    assert variable.actual_value == 0


# ---------------------------------------------------------------------------
# age / weight / imc
# ---------------------------------------------------------------------------


def test_age_without_a_value_reports_age_missing():
    """age: a patient with no age registered is AGE_MISSING"""

    variable = _evaluate(
        _get_alert_protocol(), {"field": "age", "operator": ">", "value": 60}
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.AGE_MISSING.value


def test_age_with_a_non_numeric_threshold_reports_value_not_numeric():
    """age: a threshold that is not a number is VALUE_NOT_NUMERIC"""

    variable = _evaluate(
        _get_alert_protocol(exams={"age": 70}),
        {"field": "age", "operator": ">", "value": "abc"},
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.VALUE_NOT_NUMERIC.value


def test_weight_without_a_value_reports_weight_missing():
    """weight: a patient with no weight registered is WEIGHT_MISSING"""

    variable = _evaluate(
        _get_alert_protocol(), {"field": "weight", "operator": ">", "value": 80}
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.WEIGHT_MISSING.value


def test_weight_with_a_non_numeric_threshold_reports_value_not_numeric():
    """weight: a threshold that is not a number is VALUE_NOT_NUMERIC"""

    variable = _evaluate(
        _get_alert_protocol(exams={"weight": 80}),
        {"field": "weight", "operator": ">", "value": "abc"},
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.VALUE_NOT_NUMERIC.value


def test_imc_with_a_non_numeric_threshold_reports_value_not_numeric():
    """imc: a threshold that is not a number is VALUE_NOT_NUMERIC"""

    variable = _evaluate(
        _get_alert_protocol(exams={"weight": 80, "height": 180}),
        {"field": "imc", "operator": ">", "value": "abc"},
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.VALUE_NOT_NUMERIC.value


def test_imc_with_a_negative_height_reports_height_missing():
    """imc: a height that cannot divide is HEIGHT_MISSING, not a crash"""

    variable = _evaluate(
        _get_alert_protocol(exams={"weight": 80, "height": -10}),
        {"field": "imc", "operator": ">", "value": 30},
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.HEIGHT_MISSING.value


# ---------------------------------------------------------------------------
# segmentType / idDepartment / idSegment
# ---------------------------------------------------------------------------


def test_segment_type_without_extra_info_reports_no_segment_type():
    """segmentType: no extra info carried into the evaluation is NO_SEGMENT_TYPE"""

    variable = _evaluate(
        _get_alert_protocol(),
        {"field": "segmentType", "operator": "=", "value": 1},
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.NO_SEGMENT_TYPE.value


def test_segment_type_without_a_type_reports_no_segment_type():
    """segmentType: extra info with an empty segment type is NO_SEGMENT_TYPE"""

    variable = _evaluate(
        _get_alert_protocol(protocol_extra_info=ProtocolExtraInfo()),
        {"field": "segmentType", "operator": "=", "value": 1},
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.NO_SEGMENT_TYPE.value


def test_segment_type_in_compares_as_a_list():
    """segmentType: the IN operator compares the type against a list of ints"""

    variable = _evaluate(
        _get_alert_protocol(protocol_extra_info=ProtocolExtraInfo(segment_type=2)),
        {"field": "segmentType", "operator": "IN", "value": ["1", "3"]},
    )

    assert variable.result is False
    assert variable.actual_value == [2]


def test_segment_type_equality_compares_the_scalar():
    """segmentType: a scalar operator compares the type directly"""

    variable = _evaluate(
        _get_alert_protocol(protocol_extra_info=ProtocolExtraInfo(segment_type=2)),
        {"field": "segmentType", "operator": "=", "value": 2},
    )

    assert variable.result is True
    assert variable.actual_value == 2


def test_id_department_equality_compares_the_scalar():
    """idDepartment: a scalar operator compares the department directly"""

    variable = _evaluate(
        _get_alert_protocol(),
        {"field": "idDepartment", "operator": "=", "value": 100},
    )

    assert variable.result is True
    assert variable.actual_value == 100


def test_id_segment_equality_compares_the_scalar():
    """idSegment: a scalar operator compares the segment directly"""

    prescription = Prescription()
    prescription.idSegment = 7

    variable = _evaluate(
        _get_alert_protocol(prescription=prescription),
        {"field": "idSegment", "operator": "=", "value": 7},
    )

    assert variable.result is True
    assert variable.actual_value == 7


# ---------------------------------------------------------------------------
# idIcd / tags / admissionNumber: operators the field does not support
# ---------------------------------------------------------------------------


def test_id_icd_with_a_scalar_operator_reports_operator_not_supported():
    """idIcd: only list operators are implemented; "=" is OPERATOR_NOT_SUPPORTED"""

    patient = Patient()
    patient.id_icd = "A01"

    variable = _evaluate(
        _get_alert_protocol(patient=patient),
        {"field": "idIcd", "operator": "=", "value": "A01"},
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.OPERATOR_NOT_SUPPORTED.value
    assert variable.details["operator"] == "="


def test_tags_without_a_patient_reports_no_patient():
    """tags: no patient record is NO_PATIENT"""

    alert_protocol = _get_alert_protocol()
    alert_protocol.patient = None

    variable = _evaluate(
        alert_protocol, {"field": "tags", "operator": "IN", "value": ["SEPSE"]}
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.NO_PATIENT.value


def test_tags_with_a_scalar_operator_reports_operator_not_supported():
    """tags: only IN/NOTIN are implemented for tags"""

    variable = _evaluate(
        _get_alert_protocol(),
        {"field": "tags", "operator": "=", "value": ["SEPSE"]},
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.OPERATOR_NOT_SUPPORTED.value


def test_admission_number_without_a_number_reports_no_patient():
    """admissionNumber: a patient without an admission number is NO_PATIENT"""

    variable = _evaluate(
        _get_alert_protocol(),
        {"field": "admissionNumber", "operator": "IN", "value": ["5"]},
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.NO_PATIENT.value


def test_admission_number_with_a_scalar_operator_reports_operator_not_supported():
    """admissionNumber: only IN/NOTIN are implemented"""

    patient = Patient()
    patient.admissionNumber = 5

    variable = _evaluate(
        _get_alert_protocol(patient=patient),
        {"field": "admissionNumber", "operator": "=", "value": ["5"]},
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.OPERATOR_NOT_SUPPORTED.value


# ---------------------------------------------------------------------------
# insurance
# ---------------------------------------------------------------------------


def test_insurance_without_a_value_reports_insurance_missing():
    """insurance: a prescription with no insurance is INSURANCE_MISSING"""

    variable = _evaluate(
        _get_alert_protocol(),
        {"field": "insurance", "operator": "CONTAINS", "value": "SUS"},
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.INSURANCE_MISSING.value


def test_insurance_without_a_prescription_reports_insurance_missing():
    """insurance: no prescription at all is INSURANCE_MISSING"""

    alert_protocol = _get_alert_protocol()
    alert_protocol.prescription = None

    variable = _evaluate(
        alert_protocol,
        {"field": "insurance", "operator": "CONTAINS", "value": "SUS"},
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.INSURANCE_MISSING.value


def test_insurance_matches_case_insensitively():
    """insurance: the comparison is a case-insensitive substring match"""

    prescription = Prescription()
    prescription.idDepartment = 100
    prescription.insurance = "Convênio SUS"

    variable = _evaluate(
        _get_alert_protocol(prescription=prescription),
        {"field": "insurance", "operator": "CONTAINS", "value": "sus"},
    )

    assert variable.result is True


# ---------------------------------------------------------------------------
# unsupported field / operator
# ---------------------------------------------------------------------------


def test_an_unknown_field_is_rejected():
    """_fill_variable: a field the evaluator does not know raises"""

    alert_protocol = _get_alert_protocol()

    with pytest.raises(NotImplementedError, match="field not supported"):
        alert_protocol.get_protocol_alerts(
            protocol=_single_variable_protocol(
                {"field": "unknown_field", "operator": "=", "value": 1}
            )
        )


def test_an_unknown_operator_is_rejected():
    """_compare: an operator the evaluator does not know raises"""

    alert_protocol = _get_alert_protocol()

    with pytest.raises(NotImplementedError, match="operator not supported"):
        alert_protocol.get_protocol_alerts(
            protocol=_single_variable_protocol(
                {"field": "idDepartment", "operator": "~=", "value": 100}
            )
        )


# ---------------------------------------------------------------------------
# _filter_drug_list: items the evaluation never sees
# ---------------------------------------------------------------------------


def test_suspended_items_are_left_out_of_the_evaluation():
    """_filter_drug_list: a suspended item is not part of the drug lists"""

    row = utils_test_prescription.get_prescription_drug_mock_row(
        id_prescription_drug=1, dose=10, sctid="111", drug_class="J1", route="VO"
    )
    row.prescription_drug.suspendedDate = datetime.now()

    alert_protocol = _get_alert_protocol(drug_list=[row])

    assert alert_protocol.filtered_drugs == []
    assert alert_protocol.substance_list == []


def test_items_of_an_unsupported_source_are_left_out_of_the_evaluation():
    """_filter_drug_list: only the four prescribable sources are evaluated"""

    row = utils_test_prescription.get_prescription_drug_mock_row(
        id_prescription_drug=1, dose=10, sctid="111", drug_class="J1"
    )
    row.prescription_drug.source = "Dietas especiais"

    alert_protocol = _get_alert_protocol(drug_list=[row])

    assert alert_protocol.filtered_drugs == []


def test_an_active_item_fills_the_lookup_lists():
    """_filter_drug_list: an active item feeds substance, class, drug and route"""

    row = utils_test_prescription.get_prescription_drug_mock_row(
        id_prescription_drug=1, dose=10, sctid="111", drug_class="J1", route="vo"
    )

    alert_protocol = _get_alert_protocol(drug_list=[row])

    assert alert_protocol.substance_list == ["111"]
    assert alert_protocol.class_list == ["J1"]
    assert alert_protocol.id_drug_list == ["1"]
    assert alert_protocol.route_list == ["VO"]


# ---------------------------------------------------------------------------
# _is_safe_logical_expression: the trigger guard rail
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "trigger",
    [
        "",  # nothing to evaluate
        "( ) ",  # no keyword, only structure
        "__import__('os')",  # not a logical expression
        "True and " + "(" * 500,  # over the length limit
    ],
)
def test_an_unsafe_trigger_is_refused(trigger):
    """_is_safe_logical_expression: only boolean expressions reach eval"""

    alert_protocol = _get_alert_protocol()

    with pytest.raises(ValueError, match="unsafe expression"):
        alert_protocol.get_protocol_alerts(
            protocol={"variables": [], "trigger": trigger, "result": RESULT.copy()}
        )


def test_a_boolean_trigger_is_accepted():
    """_is_safe_logical_expression: a plain boolean expression is evaluated"""

    alert_protocol = _get_alert_protocol()

    result = alert_protocol.get_protocol_alerts(
        protocol={
            "variables": [],
            "trigger": "True and not False",
            "result": RESULT.copy(),
        }
    )

    assert result["message"] == RESULT["message"]


# ---------------------------------------------------------------------------
# _get_drug_attribute_keys
# ---------------------------------------------------------------------------


def test_drug_attribute_keys_lists_every_flag_that_is_on():
    """_get_drug_attribute_keys: each enabled attribute contributes its key"""

    attributes = DrugAttributes()
    attributes.antimicro = True
    attributes.controlled = True
    attributes.chemo = True
    attributes.mav = True
    attributes.notdefault = True
    attributes.elderly = True
    attributes.dialyzable = True

    keys = _get_alert_protocol()._get_drug_attribute_keys(attributes)

    assert keys == [
        "antimicro",
        "controlled",
        "chemo",
        "mav",
        "notdefault",
        "elderly",
        "dialyzable",
    ]


def test_drug_attribute_keys_skips_flags_that_are_off_or_unset():
    """_get_drug_attribute_keys: false and null attributes contribute nothing"""

    attributes = DrugAttributes()
    attributes.antimicro = False
    attributes.controlled = None
    attributes.chemo = True

    keys = _get_alert_protocol()._get_drug_attribute_keys(attributes)

    assert keys == ["chemo"]


def test_drug_attribute_keys_without_an_attributes_row_is_empty():
    """_get_drug_attribute_keys: a drug with no attributes row has no keys"""

    assert _get_alert_protocol()._get_drug_attribute_keys(None) == []


# ---------------------------------------------------------------------------
# combination: criteria the evaluator cannot apply
# ---------------------------------------------------------------------------


def _combination_drug_list(measure_unit_nh=None):
    """One active item a combination variable can be tested against"""

    return [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=1,
            dose=10,
            frequency=2,
            period=3,
            sctid="111",
            drug_class="J1",
            measure_unit_nh=measure_unit_nh,
        )
    ]


@pytest.mark.parametrize(
    "criterion,extra",
    [
        ("dose", {"dose": "abc"}),
        ("frequencyday", {"frequencyday": "abc"}),
        ("period", {"period": "abc"}),
    ],
)
def test_a_non_numeric_combination_criterion_reports_value_not_numeric(
    criterion, extra
):
    """combination: a criterion configured with text instead of a number is
    VALUE_NOT_NUMERIC, and the trace names which criterion it was"""

    variable = _evaluate(
        _get_alert_protocol(drug_list=_combination_drug_list()),
        {"field": "combination", "substance": ["111"], **extra},
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.VALUE_NOT_NUMERIC.value
    assert variable.details["criterion"] == criterion


def test_a_combination_on_the_default_measure_unit_needs_one_registered():
    """combination: an item with no measure unit row is MEASURE_UNIT_MISSING"""

    # no measure unit row at all: the criterion has nothing to compare against
    drug_list = [_combination_drug_list()[0]._replace(measure_unit=None)]

    variable = _evaluate(
        _get_alert_protocol(drug_list=drug_list),
        {
            "field": "combination",
            "substance": ["111"],
            "defaultMeasureUnit": "mg",
        },
    )

    assert variable.result is False
    assert variable.reason == TraceReasonEnum.MEASURE_UNIT_MISSING.value
    assert variable.details["criterion"] == "defaultMeasureUnit"


def test_a_combination_matches_when_every_criterion_holds():
    """combination: the trace reports a match and the item that produced it"""

    trace = _get_alert_protocol(
        drug_list=_combination_drug_list(measure_unit_nh="mg")
    ).evaluate_with_trace(
        protocol=_single_variable_protocol(
            {
                "field": "combination",
                "substance": ["111"],
                "dose": 10,
                "frequencyday": 2,
                "defaultMeasureUnit": "mg",
            }
        )
    )

    variable = trace["variables"][0]

    assert trace["activated"] is True
    assert variable.reason == TraceReasonEnum.COMBINATION_MATCHED.value
    assert trace["related_items"] == [1]


# ---------------------------------------------------------------------------
# _compare / _trace_compare
# ---------------------------------------------------------------------------


def test_the_not_equal_operator_is_supported():
    """_compare: "!=" compares the scalar values"""

    variable = _evaluate(
        _get_alert_protocol(),
        {"field": "idDepartment", "operator": "!=", "value": 999},
    )

    assert variable.result is True


def test_an_unorderable_match_detail_does_not_break_the_evaluation():
    """_trace_compare: the "matched" detail is best effort — an intersection
    that cannot be sorted (a protocol mixing numbers and text) is dropped
    instead of failing the whole evaluation"""

    drug_list = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=1, dose=10, sctid="111", drug_class=1
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=2, dose=10, sctid="222", drug_class="J1"
        ),
    ]

    variable = _evaluate(
        _get_alert_protocol(drug_list=drug_list),
        {"field": "class", "operator": "IN", "value": [1, "J1"]},
    )

    assert variable.result is True
    assert variable.reason == TraceReasonEnum.COMPARED.value
    assert "matched" not in variable.details
