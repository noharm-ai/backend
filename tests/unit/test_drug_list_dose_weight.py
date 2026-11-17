"""Unit tests for the per-item clinical data ``DrugList._process_drugs`` derives.

``_process_drugs`` turns each prescription row into the dictionary the drug list
screen renders. Besides copying fields, it derives a few values the pharmacist
actually reads:

* **dose per weight** — ``doseWeight`` (dose/Kg) and ``doseWeightDay``
  (dose/Kg/Dia), optionally followed by the same dose expressed in the drug's
  default measure unit (``ou 2 mg/Kg``) when a conversion is configured;
* **dose per body surface** — ``doseBodySurface`` (dose/m²), only for
  chemotherapy drugs, using the Mosteller body-surface formula;
* **tubeAlert** — the drug is flagged as unsuitable for a feeding tube and the
  item is prescribed through one;
* **dialyzable** — the drug is dialyzable and the patient is on dialysis;
* **prevNotes / prevNotesUser** — the previous recommendation, where the author
  name is wrapped in the ``##@...@##`` markers the query adds.

The constructor only needs the attributes exercised here, so the rows are plain
fakes reproducing the dual (positional + attribute) interface of a SQLAlchemy
``Row``. ``DrugList.__init__`` runs ``_process_drugs`` itself, so building the
object is what runs the code under test.
"""

import math
from types import SimpleNamespace

import pytest

from models.enums import DrugTypeEnum
from utils.drug_list import DrugList


class _FakeRow:
    """Minimal stand-in for a SQLAlchemy Row: positional + attribute access."""

    def __init__(self, items, **attrs):
        self._items = list(items)
        for key, value in attrs.items():
            setattr(self, key, value)

    def __getitem__(self, index):
        return self._items[index]


def _drug_attributes(**overrides):
    """DrugAttributes stand-in with every field ``drug_service.to_dict`` reads."""
    attributes = {
        "antimicro": False,
        "mav": False,
        "controlled": False,
        "notdefault": False,
        "maxDose": None,
        "kidney": None,
        "liver": None,
        "platelets": None,
        "elderly": False,
        "tube": False,
        "division": None,
        "useWeight": False,
        "idMeasureUnit": None,
        "idMeasureUnitPrice": None,
        "amount": None,
        "amountUnit": None,
        "price": None,
        "maxTime": None,
        "fallRisk": None,
        "whiteList": False,
        "chemo": False,
        "dialyzable": False,
        "pregnant": None,
        "lactating": None,
        "fasting": None,
    }
    attributes.update(overrides)
    return SimpleNamespace(**attributes)


def _prescription_drug(**overrides):
    """PrescriptionDrug stand-in (pd[0]) with the fields the method touches."""
    prescription_drug = {
        "id": 1,
        "idPrescription": 10,
        "idDrug": 100,
        "idSegment": 1,
        "source": DrugTypeEnum.DRUG.value,
        "dose": None,
        "doseconv": None,
        "differentiated_dose": None,
        "idMeasureUnit": None,
        "frequency": None,
        "idFrequency": None,
        "interval": None,
        "notes": None,
        "period": None,
        "tp_period": None,
        "period_total": None,
        "route": "ORAL",
        "allergy": "N",
        "suspendedDate": None,
        "tube": False,
        "checked": False,
        "status": "0",
        "near": False,
        "cpoe_group": None,
        "solutionGroup": None,
        "solutionACM": None,
        "solutionPhase": None,
        "solutionTime": None,
        "solutionTotalTime": None,
        "solutionDose": None,
        "solutionUnit": None,
        "form": None,
        "schedule": None,
        "order_number": None,
        "intravenous": False,
    }
    prescription_drug.update(overrides)
    return SimpleNamespace(**prescription_drug)


_SAME_AS_ID = object()  # _row: the unit's normalized name is its id


def _row(
    prescription_drug=None,
    attributes=None,
    measure_unit="mg",
    prev_notes=None,
    convert_factor=None,
    measure_unit_nh=_SAME_AS_ID,
    default_measure_unit_nh=None,
):
    """Build a prescription row shaped like the ones ``_process_drugs`` consumes.
    The prescribed unit's normalized name is its id unless given (None for none)."""
    items = [
        prescription_drug if prescription_drug is not None else _prescription_drug(),
        SimpleNamespace(name="Medicamento Teste", sctid=None),  # 1 Drug
        SimpleNamespace(  # 2 MeasureUnit
            id=measure_unit,
            description=measure_unit,
            measureunit_nh=measure_unit
            if measure_unit_nh is _SAME_AS_ID
            else measure_unit_nh,
        )
        if measure_unit is not None
        else None,
        None,  # 3 Frequency
        None,  # 4
        0,  # 5 score
        attributes if attributes is not None else _drug_attributes(),  # 6
        None,  # 7 notes
        prev_notes,  # 8 previous notes
        None,  # 9 checked flag
        None,  # 10
        None,  # 11 Substance
        None,  # 12 cpoe period
    ]
    return _FakeRow(
        items,
        idDepartment=1,
        prescription_date=None,
        prescription_expire=None,
        default_measure_unit_nh=default_measure_unit_nh,
        measure_unit_convert_factor=convert_factor,
        measure_unit_solution_convert_factor=None,
    )


def _process(rows, exams=None, dialysis=None, is_cpoe=False):
    """Run ``_process_drugs`` (via the constructor) and return the result rows."""
    drug_list = DrugList(
        drugList=rows,
        interventions=[],
        relations={"stats": {}, "alerts": {}},
        exams=exams,
        agg=False,
        dialysis=dialysis,
        alerts={"stats": {}, "alerts": {}},
        admission_number=1,
        is_cpoe=is_cpoe,
    )
    return drug_list.drug_results


def _exams(weight=None, height=None):
    """The exams dict the drug list reads the patient measurements from."""
    return {"weight": weight, "height": height}


class TestSourceFiltering:
    """Which prescription rows make it into the drug list at all."""

    def test_missing_source_defaults_to_medicamentos(self):
        """A row with no source is treated as a regular drug."""
        results = _process([_row(_prescription_drug(source=None))])
        assert len(results) == 1
        assert results[0]["source"] == DrugTypeEnum.DRUG.value

    @pytest.mark.parametrize(
        "source",
        [
            DrugTypeEnum.DRUG.value,
            DrugTypeEnum.SOLUTION.value,
            DrugTypeEnum.PROCEDURE.value,
            DrugTypeEnum.DIET.value,
        ],
    )
    def test_known_sources_are_kept(self, source):
        """Every source the drug list renders produces a row."""
        results = _process([_row(_prescription_drug(source=source))])
        assert len(results) == 1
        assert results[0]["source"] == source

    def test_unknown_source_is_skipped(self):
        """A source the screen has no tab for is dropped instead of rendered."""
        assert _process([_row(_prescription_drug(source="Hemocomponentes"))]) == []


class TestDosePerWeight:
    """``doseWeight`` / ``doseWeightDay``: dose normalized by the patient weight."""

    def test_no_exams_leaves_dose_per_weight_empty(self):
        """Without exam data there is no weight to divide by."""
        results = _process([_row(_prescription_drug(dose=100, frequency=2))])
        assert results[0]["doseWeight"] is None
        assert results[0]["doseWeightDay"] is None

    def test_zero_weight_leaves_dose_per_weight_empty(self):
        """A patient with no registered weight gets no dose/Kg."""
        results = _process(
            [_row(_prescription_drug(dose=100, frequency=2))], exams=_exams(weight=0)
        )
        assert results[0]["doseWeight"] is None

    def test_dose_per_kg_is_formatted_with_the_prescribed_unit(self):
        """100 mg for a 50 Kg patient is reported as 2 mg/Kg."""
        results = _process(
            [_row(_prescription_drug(dose=100, frequency=2))],
            exams=_exams(weight=50),
        )
        assert results[0]["doseWeight"] == "2,00 mg/Kg"
        assert results[0]["doseWeightValue"] == "2,00"

    def test_daily_dose_multiplies_by_the_frequency(self):
        """The daily value is the dose/Kg times the number of daily doses."""
        results = _process(
            [_row(_prescription_drug(dose=100, frequency=3))],
            exams=_exams(weight=50),
        )
        assert results[0]["doseWeightDay"] == "6,00 mg/Kg/Dia"
        assert results[0]["doseWeightDayValue"] == "6,00"

    def test_decimal_dose_uses_brazilian_separator(self):
        """Fractional values keep the comma the Brazilian UI expects."""
        results = _process(
            [_row(_prescription_drug(dose=100, frequency=1))],
            exams=_exams(weight=40),
        )
        assert results[0]["doseWeight"] == "2,50 mg/Kg"

    def test_zero_frequency_has_no_daily_dose(self):
        """An item without a daily frequency reports only the dose/Kg."""
        results = _process(
            [_row(_prescription_drug(dose=100, frequency=0))],
            exams=_exams(weight=50),
        )
        assert results[0]["doseWeight"] == "2,00 mg/Kg"
        assert results[0]["doseWeightDay"] is None

    @pytest.mark.parametrize("frequency", [33, 44, 55, 66, 99])
    def test_special_frequency_codes_have_no_daily_dose(self, frequency):
        """ACM/SN style frequency codes are counts, not doses per day."""
        results = _process(
            [_row(_prescription_drug(dose=100, frequency=frequency))],
            exams=_exams(weight=50),
        )
        assert results[0]["doseWeight"] == "2,00 mg/Kg"
        assert results[0]["doseWeightDay"] is None

    def test_no_dose_leaves_dose_per_weight_empty(self):
        """An item with no prescribed dose has nothing to normalize."""
        results = _process(
            [_row(_prescription_drug(dose=None, frequency=2))],
            exams=_exams(weight=50),
        )
        assert results[0]["doseWeight"] is None


class TestMissingConvertFactor:
    """missingConvertFactor: the screen marks an item whose dose can't be
    converted to the drug's default unit (no unidadeconverte factor)."""

    def _flag(
        self,
        unit="mg",
        default_unit="mcg",
        convert_factor=None,
        unit_nh=_SAME_AS_ID,
        default_unit_nh=None,
    ):
        """missingConvertFactor of one item prescribed in ``unit``."""
        results = _process(
            [
                _row(
                    _prescription_drug(dose=100, frequency=2, idMeasureUnit=unit),
                    attributes=_drug_attributes(idMeasureUnit=default_unit),
                    measure_unit=unit,
                    convert_factor=convert_factor,
                    measure_unit_nh=unit_nh,
                    default_measure_unit_nh=default_unit_nh,
                )
            ]
        )
        return results[0]["missingConvertFactor"]

    def test_another_unit_without_a_factor_is_missing(self):
        """Prescribed in mg, default mcg and no factor"""
        assert self._flag() is True

    def test_another_unit_with_a_factor_is_not_missing(self):
        """The factor converts the dose"""
        assert self._flag(convert_factor=1000) is False

    def test_default_unit_needs_no_factor(self):
        """Prescribed in the default unit there is nothing to convert"""
        assert self._flag(unit="mcg") is False

    def test_drug_without_a_default_unit_is_not_flagged(self):
        """Without a default unit there is no unit to convert to"""
        assert self._flag(default_unit=None) is False

    def test_same_normalized_unit_is_not_flagged(self):
        """MILIGRAMA and mg are the same unit (unidademedida_nh): nothing to convert"""
        assert (
            self._flag(
                unit="MILIGRAMA", default_unit="mg", unit_nh="mg", default_unit_nh="mg"
            )
            is False
        )

    def test_different_normalized_units_are_flagged(self):
        """Both units normalized, but to different ones"""
        assert (
            self._flag(
                unit="COMPRIMIDO", default_unit="mg", unit_nh="un", default_unit_nh="mg"
            )
            is True
        )

    def test_prescribed_unit_without_normalized_name_is_flagged(self):
        """Without unidademedida_nh on the prescribed unit it can't be told the same"""
        assert (
            self._flag(
                unit="AMPOLA", default_unit="mg", unit_nh=None, default_unit_nh="mg"
            )
            is True
        )

    def test_item_without_a_unit_is_not_flagged(self):
        """Without a prescribed unit there is nothing to convert from"""
        assert self._flag(unit=None) is False


class TestDosePerWeightConversion:
    """The "ou X unidade/Kg" suffix shown when the drug has a default unit."""

    def test_converted_dose_is_appended(self):
        """The converted dose/Kg follows the prescribed one."""
        attributes = _drug_attributes(idMeasureUnit="mcg", useWeight=False)
        results = _process(
            [
                _row(
                    _prescription_drug(dose=100, frequency=2, doseconv=100000),
                    attributes=attributes,
                    convert_factor=1000,
                )
            ],
            exams=_exams(weight=50),
        )
        assert results[0]["doseWeight"] == "2,00 mg/Kg ou 2.000,00 mcg/Kg"
        assert results[0]["doseWeightDay"] == "4,00 mg/Kg/Dia ou 4.000,00 mcg/Kg/Dia"

    def test_no_conversion_factor_has_no_converted_dose(self):
        """Without a factor prescalc stores the dose unconverted, in the
        prescribed unit: it is not shown under the default unit."""
        attributes = _drug_attributes(idMeasureUnit="mcg")
        results = _process(
            [
                _row(
                    # doseconv = the 100 mg as prescribed, not 100.000 mcg
                    _prescription_drug(dose=100, frequency=2, doseconv=100),
                    attributes=attributes,
                )
            ],
            exams=_exams(weight=50),
        )
        assert results[0]["doseWeight"] == "2,00 mg/Kg"
        assert results[0]["doseWeightDay"] == "4,00 mg/Kg/Dia"

    def test_doseconv_stored_before_the_factor_is_not_used(self):
        """prescalc ran before the mg -> mcg factor was registered, so it
        stored the 100 mg unconverted: the current factor converts the dose."""
        attributes = _drug_attributes(idMeasureUnit="mcg")
        results = _process(
            [
                _row(
                    _prescription_drug(dose=100, frequency=2, doseconv=100),
                    attributes=attributes,
                    convert_factor=1000,
                )
            ],
            exams=_exams(weight=50),
        )
        assert results[0]["doseWeight"] == "2,00 mg/Kg ou 2.000,00 mcg/Kg"
        assert results[0]["doseWeightDay"] == "4,00 mg/Kg/Dia ou 4.000,00 mcg/Kg/Dia"

    def test_dose_range_drug_ignores_the_rounded_doseconv(self):
        """A range drug's doseconv is the outlier range, rounded up and divided
        by the weight prescalc found: the prescribed dose is converted instead."""
        attributes = _drug_attributes(idMeasureUnit="mcg", useWeight=True, division=10)
        results = _process(
            [
                _row(
                    # 100 mg / 50 Kg = 2.000 mcg/Kg, stored as its range: 2.010
                    _prescription_drug(dose=100, frequency=2, doseconv=2010),
                    attributes=attributes,
                    convert_factor=1000,
                )
            ],
            exams=_exams(weight=50),
        )
        assert results[0]["doseWeight"] == "2,00 mg/Kg ou 2.000,00 mcg/Kg"
        assert results[0]["doseWeightDay"] == "4,00 mg/Kg/Dia ou 4.000,00 mcg/Kg/Dia"

    def test_dose_range_drug_calculated_without_a_weight(self):
        """When prescalc ran before the weight was known it divided by 1, so
        doseconv is the whole dose; the current weight is used instead."""
        attributes = _drug_attributes(idMeasureUnit="mcg", useWeight=True, division=10)
        results = _process(
            [
                _row(
                    _prescription_drug(dose=100, frequency=2, doseconv=100000),
                    attributes=attributes,
                    convert_factor=1000,
                )
            ],
            exams=_exams(weight=50),
        )
        assert results[0]["doseWeight"] == "2,00 mg/Kg ou 2.000,00 mcg/Kg"
        assert "faixa arredondada" not in results[0]["doseWeight"]

    def test_dose_range_drug_without_weight_flag(self):
        """Ranges without the weight still round doseconv up, so it is not used."""
        attributes = _drug_attributes(idMeasureUnit="mcg", division=500)
        results = _process(
            [
                _row(
                    # 0,3 mg = 300 mcg, stored as its range: 500
                    _prescription_drug(dose=0.3, frequency=1, doseconv=500),
                    attributes=attributes,
                    convert_factor=1000,
                )
            ],
            exams=_exams(weight=3),
        )
        assert results[0]["doseWeight"] == "0,10 mg/Kg ou 100,00 mcg/Kg"

    def test_dose_range_drug_without_a_conversion_factor(self):
        """Without a factor for the prescribed unit there is no converted dose."""
        attributes = _drug_attributes(idMeasureUnit="mcg", useWeight=True, division=10)
        results = _process(
            [
                _row(
                    _prescription_drug(dose=100, frequency=2, doseconv=2010),
                    attributes=attributes,
                )
            ],
            exams=_exams(weight=50),
        )
        assert results[0]["doseWeight"] == "2,00 mg/Kg"
        assert results[0]["doseWeightDay"] == "4,00 mg/Kg/Dia"

    def test_same_unit_under_another_id_is_not_converted(self):
        """MILIGRAMA and mg normalize to mg: the same unit, no "ou ..." part"""
        attributes = _drug_attributes(idMeasureUnit="mg")
        results = _process(
            [
                _row(
                    _prescription_drug(
                        dose=100, frequency=2, doseconv=100, idMeasureUnit="MILIGRAMA"
                    ),
                    attributes=attributes,
                    measure_unit="MILIGRAMA",
                    measure_unit_nh="mg",
                    default_measure_unit_nh="mg",
                    convert_factor=1,
                )
            ],
            exams=_exams(weight=50),
        )
        assert results[0]["doseWeight"] == "2,00 MILIGRAMA/Kg"
        assert results[0]["doseWeightDay"] == "4,00 MILIGRAMA/Kg/Dia"

    def test_same_unit_is_not_converted(self):
        """When the default unit equals the prescribed one there is nothing to show."""
        attributes = _drug_attributes(idMeasureUnit="mg")
        results = _process(
            [
                _row(
                    _prescription_drug(dose=100, frequency=2, doseconv=100),
                    attributes=attributes,
                )
            ],
            exams=_exams(weight=50),
        )
        assert results[0]["doseWeight"] == "2,00 mg/Kg"

    def test_missing_doseconv_is_not_converted(self):
        """Without a converted dose the suffix is omitted."""
        attributes = _drug_attributes(idMeasureUnit="g")
        results = _process(
            [
                _row(
                    _prescription_drug(dose=100, frequency=2, doseconv=None),
                    attributes=attributes,
                )
            ],
            exams=_exams(weight=50),
        )
        assert results[0]["doseWeight"] == "2,00 mg/Kg"


class TestDosePerBodySurface:
    """``doseBodySurface``: dose/m², shown for chemotherapy drugs."""

    def test_chemo_dose_uses_the_mosteller_body_surface(self):
        """The dose is divided by sqrt(weight * height / 3600)."""
        attributes = _drug_attributes(chemo=True)
        results = _process(
            [_row(_prescription_drug(dose=100), attributes=attributes)],
            exams=_exams(weight=70, height=170),
        )
        body_surface = math.sqrt((70 * 170) / 3600)
        expected = f"{round(100 / body_surface, 2):_.2f}".replace(".", ",")
        assert results[0]["doseBodySurface"] == f"{expected} mg/m²"

    def test_non_chemo_drug_has_no_body_surface_dose(self):
        """Only chemotherapy drugs are reported per square metre."""
        results = _process(
            [_row(_prescription_drug(dose=100))],
            exams=_exams(weight=70, height=170),
        )
        assert results[0]["doseBodySurface"] is None

    def test_missing_height_has_no_body_surface_dose(self):
        """Body surface needs both measurements; without height it is omitted."""
        attributes = _drug_attributes(chemo=True)
        results = _process(
            [_row(_prescription_drug(dose=100), attributes=attributes)],
            exams=_exams(weight=70, height=None),
        )
        assert results[0]["doseBodySurface"] is None

    def test_missing_dose_has_no_body_surface_dose(self):
        """An item with no dose has nothing to express per square metre."""
        attributes = _drug_attributes(chemo=True)
        results = _process(
            [_row(_prescription_drug(dose=None), attributes=attributes)],
            exams=_exams(weight=70, height=170),
        )
        assert results[0]["doseBodySurface"] is None


class TestTubeAlert:
    """``tubeAlert``: drug unsuitable for administration through a feeding tube."""

    def test_alert_when_drug_and_item_are_both_flagged(self):
        """The alert needs the drug attribute and the item route to agree."""
        attributes = _drug_attributes(tube=True)
        results = _process(
            [_row(_prescription_drug(tube=True), attributes=attributes)],
            exams=_exams(weight=50),
        )
        assert results[0]["tubeAlert"] is True

    def test_no_alert_when_the_item_is_not_through_a_tube(self):
        """A tube-flagged drug prescribed by another route raises no alert."""
        attributes = _drug_attributes(tube=True)
        results = _process(
            [_row(_prescription_drug(tube=False), attributes=attributes)],
            exams=_exams(weight=50),
        )
        assert results[0]["tubeAlert"] is False

    def test_no_alert_for_a_suspended_item(self):
        """A suspended item is not being administered, so it raises no alert."""
        from datetime import datetime

        attributes = _drug_attributes(tube=True)
        results = _process(
            [
                _row(
                    _prescription_drug(tube=True, suspendedDate=datetime(2026, 1, 1)),
                    attributes=attributes,
                )
            ],
            exams=_exams(weight=50),
        )
        assert results[0]["tubeAlert"] is False

    def test_no_alert_without_exams(self):
        """The tube check runs inside the exam-dependent block."""
        attributes = _drug_attributes(tube=True)
        results = _process([_row(_prescription_drug(tube=True), attributes=attributes)])
        assert results[0]["tubeAlert"] is False


class TestDialyzable:
    """``dialyzable``: dialyzable drug prescribed to a patient on dialysis."""

    def test_flagged_for_a_patient_on_dialysis(self):
        """Both conditions together raise the flag."""
        attributes = _drug_attributes(dialyzable=True)
        results = _process([_row(attributes=attributes)], dialysis="1")
        assert results[0]["dialyzable"] is True

    def test_not_flagged_without_dialysis(self):
        """A dialyzable drug alone is not a finding."""
        attributes = _drug_attributes(dialyzable=True)
        results = _process([_row(attributes=attributes)], dialysis=None)
        assert results[0]["dialyzable"] is False

    def test_dialysis_zero_counts_as_no_dialysis(self):
        """A dialysis flag of "0" means the patient is not on dialysis."""
        attributes = _drug_attributes(dialyzable=True)
        results = _process([_row(attributes=attributes)], dialysis="0")
        assert results[0]["dialyzable"] is False

    def test_not_flagged_for_a_non_dialyzable_drug(self):
        """A patient on dialysis does not make every drug dialyzable."""
        results = _process([_row()], dialysis="1")
        assert results[0]["dialyzable"] is False


class TestPreviousNotes:
    """``prevNotes`` / ``prevNotesUser``: the previous recommendation and its author."""

    def test_author_markers_become_parentheses(self):
        """``##@name@##`` is rendered as "(name)" in the attributed version."""
        results = _process([_row(prev_notes="Manter dose ##@Fulano Beltrano@##")])
        assert results[0]["prevNotesUser"] == "Manter dose (Fulano Beltrano)"

    def test_author_is_stripped_from_the_plain_version(self):
        """The plain note keeps only the recommendation text."""
        results = _process([_row(prev_notes="Manter dose ##@Fulano Beltrano@##")])
        assert results[0]["prevNotes"] == "Manter dose "

    def test_no_previous_note_leaves_both_empty(self):
        """Nothing to show when the item has no previous recommendation."""
        results = _process([_row(prev_notes=None)])
        assert results[0]["prevNotes"] is None
        assert results[0]["prevNotesUser"] is None
