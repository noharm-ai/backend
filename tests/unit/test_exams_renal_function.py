"""Tests: the renal function calculations derived from a creatinina exam
(exams_service._add_creatinina_calcs, _history_calc and _fill_custom_exams).

The hospital does not send a creatinine clearance: whenever the exam list of an
admission carries a creatinina result, the backend derives the clearance itself
and publishes it next to the real exams. Six calculations exist -- MDRD, CKD-EPI,
CKD-EPI 2021, Cockcroft-Gault and Schwartz 1 and 2 -- and each one is derived
only when the segment has that calculated exam configured.

The arithmetic of each formula lives in utils/examutils.py. What is pinned here
is the layer above it, which the exam card of the prescription depends on:

* which calculations are derived and which are skipped (not configured in the
  segment, already reported by the hospital, no patient, no usable creatinina);
* where the name, the reference range and the alert flag come from -- the
  segment configuration overrides what the formula itself suggests;
* the date, taken from the creatinina exam, and the history, derived entry by
  entry from the creatinina history so the clearance can be plotted over time.
"""

from datetime import datetime

import pytest

from models.prescription import Patient
from services import exams_service
from utils import examutils

# every calculation the service knows how to derive, in the order it derives them
CALC_TYPES = ["mdrd", "ckd", "ckd21", "cg", "swrtz2", "swrtz1"]

CREATININA = 1.4
EXAM_DATE = "2026-01-10T08:00:00"


class _ExamRef:
    """The segmentoexame row the service reads a calculated exam's setup from."""

    def __init__(self, type_exam, min_value=50, max_value=120):
        self.initials = type_exam.upper()
        self.name = f"Clearance {type_exam.upper()}"
        self.min = min_value
        self.max = max_value
        self.ref = f"referencia {type_exam}"
        self.tp_exam_ref = f"ref_{type_exam}"


class _Creatinina:
    """The creatinina exam the calculations are based on."""

    def __init__(self, value=CREATININA):
        self.value = value


def seg_exam(*type_exams, min_value=50, max_value=120):
    """A segment configuration carrying only the given calculated exams."""
    return {
        type_exam: _ExamRef(type_exam, min_value=min_value, max_value=max_value)
        for type_exam in type_exams
    }


def patient(
    birthdate=datetime(1980, 1, 1),
    gender="M",
    weight=70.0,
    height=170.0,
    skin_color="Branca",
):
    """A patient carrying everything the six formulas may read."""
    record = Patient()
    record.idPatient = 1
    record.admissionNumber = 1
    record.birthdate = birthdate
    record.gender = gender
    record.weight = weight
    record.height = height
    record.skinColor = skin_color

    return record


def exam_item(date=EXAM_DATE, history=None):
    """The already formatted creatinina entry of the exam card."""
    return {"date": date, "history": [] if history is None else history}


def history_entry(value, date):
    """One creatinina entry as _history_exam leaves it."""
    return {"value": value, "date": date}


def expected_value(type_exam, value, record):
    """What the formula itself answers for a creatinina value."""
    calc = {
        "mdrd": lambda: examutils.mdrd_calc(
            value, record.birthdate, record.gender, record.skinColor
        ),
        "ckd": lambda: examutils.ckd_calc(
            value,
            record.birthdate,
            record.gender,
            record.skinColor,
            record.height,
            record.weight,
        ),
        "ckd21": lambda: examutils.ckd_calc_21(value, record.birthdate, record.gender),
        "cg": lambda: examutils.cg_calc(
            value, record.birthdate, record.gender, record.weight
        ),
        "swrtz2": lambda: examutils.schwartz2_calc(value, record.height),
        "swrtz1": lambda: examutils.schwartz1_calc(
            value, record.birthdate, record.gender, record.height
        ),
    }[type_exam]

    return calc()["value"]


def derive(
    creatinina=CREATININA,
    record=None,
    configured=None,
    reported_exams=None,
    item=None,
):
    """Run _add_creatinina_calcs and return the buffer it wrote into."""
    buffer_list = {}
    exams_service._add_creatinina_calcs(
        exam=_Creatinina(creatinina),
        exam_item=item if item is not None else exam_item(),
        patient=patient() if record is None else record,
        seg_exam=seg_exam(*CALC_TYPES) if configured is None else configured,
        buffer_list=buffer_list,
        reported_exams=[] if reported_exams is None else reported_exams,
    )

    return buffer_list


class TestDerivedCalculations:
    """Teste exams_service - _add_creatinina_calcs: quais cálculos são derivados"""

    def test_derives_every_calculation_configured_in_the_segment(self):
        """Todos os cálculos configurados no segmento devem ser derivados"""
        assert sorted(derive().keys()) == sorted(CALC_TYPES)

    @pytest.mark.parametrize("type_exam", CALC_TYPES)
    def test_value_comes_from_the_formula(self, type_exam):
        """O valor derivado deve ser o da fórmula correspondente"""
        record = patient()

        result = derive(record=record)

        assert result[type_exam]["value"] == expected_value(
            type_exam, CREATININA, record
        )

    def test_skips_a_calculation_the_segment_does_not_configure(self):
        """Cálculo não configurado no segmento não deve ser derivado"""
        result = derive(configured=seg_exam("mdrd", "cg"))

        assert sorted(result.keys()) == ["cg", "mdrd"]

    def test_does_not_overwrite_a_calculation_reported_by_the_hospital(self):
        """Cálculo já enviado pelo hospital não deve ser sobrescrito"""
        result = derive(reported_exams=["mdrd", "ckd"])

        assert "mdrd" not in result
        assert "ckd" not in result
        assert "cg" in result

    def test_without_a_patient_nothing_is_derived(self):
        """Sem paciente nenhum cálculo é possível"""
        buffer_list = {}
        exams_service._add_creatinina_calcs(
            exam=_Creatinina(),
            exam_item=exam_item(),
            patient=None,
            seg_exam=seg_exam(*CALC_TYPES),
            buffer_list=buffer_list,
            reported_exams=[],
        )

        assert buffer_list == {}

    def test_a_creatinina_without_a_number_derives_nothing(self):
        """Creatinina sem valor numérico não gera cálculo"""
        assert derive(creatinina=None) == {}

    def test_a_zero_creatinina_derives_nothing(self):
        """Creatinina zerada resulta em clearance zero, que não é publicado"""
        assert derive(creatinina=0) == {}

    def test_a_patient_without_birthdate_only_derives_schwartz_2(self):
        """Sem data de nascimento resta apenas o Schwartz 2, que não usa idade"""
        result = derive(record=patient(birthdate=None))

        assert sorted(result.keys()) == ["swrtz2"]

    def test_a_patient_without_height_or_weight_skips_the_formulas_that_need_them(self):
        """Sem altura e peso, Cockcroft-Gault e os Schwartz não são derivados"""
        result = derive(record=patient(height=None, weight=None))

        assert sorted(result.keys()) == ["ckd", "ckd21", "mdrd"]


class TestDerivedCalculationSetup:
    """Teste exams_service - _add_creatinina_calcs: configuração do exame derivado"""

    @pytest.mark.parametrize("type_exam", CALC_TYPES)
    def test_name_and_reference_come_from_the_segment_configuration(self, type_exam):
        """Nome, abreviação, referência e faixa vêm da configuração do segmento"""
        configured = seg_exam(*CALC_TYPES)

        result = derive(configured=configured)[type_exam]

        assert result["name"] == configured[type_exam].name
        assert result["initials"] == configured[type_exam].initials
        assert result["ref"] == configured[type_exam].ref
        assert result["min"] == configured[type_exam].min
        assert result["max"] == configured[type_exam].max
        assert result["tp_exam_ref"] == configured[type_exam].tp_exam_ref

    @pytest.mark.parametrize("type_exam", CALC_TYPES)
    def test_no_alert_when_the_value_is_inside_the_configured_range(self, type_exam):
        """Valor dentro da faixa configurada não deve alertar"""
        result = derive(configured=seg_exam(*CALC_TYPES, min_value=0, max_value=1000))

        assert result[type_exam]["alert"] is False

    @pytest.mark.parametrize("type_exam", CALC_TYPES)
    def test_alert_when_the_value_is_outside_the_configured_range(self, type_exam):
        """Valor fora da faixa configurada deve alertar"""
        result = derive(
            configured=seg_exam(*CALC_TYPES, min_value=5000, max_value=6000)
        )

        assert result[type_exam]["alert"] is True

    @pytest.mark.parametrize("type_exam", CALC_TYPES)
    def test_the_derived_exam_is_always_flagged_as_configured(self, type_exam):
        """O exame derivado é publicado como configurado e sem percentual"""
        result = derive()[type_exam]

        assert result["configured"] is True
        assert result["perc"] is None

    @pytest.mark.parametrize("type_exam", CALC_TYPES)
    def test_date_comes_from_the_creatinina_exam(self, type_exam):
        """A data do cálculo é a da creatinina que o originou"""
        result = derive(item=exam_item(date="2026-02-03T10:20:00"))

        assert result[type_exam]["date"] == "2026-02-03T10:20:00"


class TestDerivedHistory:
    """Teste exams_service - _add_creatinina_calcs: histórico derivado"""

    def test_history_follows_the_creatinina_history(self):
        """O histórico do cálculo acompanha o histórico da creatinina"""
        record = patient()
        history = [
            history_entry(1.4, "2026-01-10T08:00:00"),
            history_entry(2.6, "2026-01-09T08:00:00"),
        ]

        result = derive(record=record, item=exam_item(history=history))["mdrd"]

        assert [entry["date"] for entry in result["history"]] == [
            "2026-01-10T08:00:00",
            "2026-01-09T08:00:00",
        ]
        assert [entry["value"] for entry in result["history"]] == [
            expected_value("mdrd", 1.4, record),
            expected_value("mdrd", 2.6, record),
        ]

    def test_history_is_empty_when_the_creatinina_has_none(self):
        """Creatinina sem histórico gera cálculo sem histórico"""
        assert derive()["mdrd"]["history"] == []


class TestHistoryCalc:
    """Teste exams_service - _history_calc"""

    @pytest.mark.parametrize("type_exam", CALC_TYPES)
    def test_calculates_every_entry_of_the_history(self, type_exam):
        """Cada entrada do histórico recebe o cálculo e mantém a sua data"""
        record = patient()
        history = [
            history_entry(1.0, "2026-01-10T08:00:00"),
            history_entry(3.2, "2026-01-08T08:00:00"),
            history_entry(0.8, "2026-01-05T08:00:00"),
        ]

        results = exams_service._history_calc(
            type_exam, history, record, seg_exam(*CALC_TYPES)
        )

        assert len(results) == len(history)
        for entry, source in zip(results, history):
            assert entry["date"] == source["date"]
            assert entry["value"] == expected_value(type_exam, source["value"], record)

    def test_applies_the_segment_configuration_to_every_entry(self):
        """A configuração do segmento é aplicada a todas as entradas do histórico"""
        configured = seg_exam(*CALC_TYPES, min_value=0, max_value=1000)

        results = exams_service._history_calc(
            "cg",
            [history_entry(1.4, EXAM_DATE), history_entry(2.8, EXAM_DATE)],
            patient(),
            configured,
        )

        for entry in results:
            assert entry["name"] == configured["cg"].name
            assert entry["min"] == 0
            assert entry["max"] == 1000
            assert entry["alert"] is False

    def test_an_unconfigured_calculation_keeps_the_formula_defaults(self):
        """Cálculo fora da configuração do segmento mantém os rótulos da fórmula"""
        results = exams_service._history_calc(
            "mdrd", [history_entry(1.4, EXAM_DATE)], patient(), seg_exam("cg")
        )

        assert results[0]["initials"] == "MDRD"
        assert results[0]["min"] == 50

    def test_an_unknown_exam_type_only_carries_the_date(self):
        """Tipo de exame que não é um cálculo devolve apenas a data"""
        results = exams_service._history_calc(
            "sodio", [history_entry(140, EXAM_DATE)], patient(), seg_exam(*CALC_TYPES)
        )

        assert results == [{"date": EXAM_DATE}]

    def test_an_empty_history_returns_no_entries(self):
        """Histórico vazio não gera entradas"""
        assert (
            exams_service._history_calc("mdrd", [], patient(), seg_exam(*CALC_TYPES))
            == []
        )
