"""Unit tests for services.alert_service dose-aggregation helpers.

`_get_dose_conv` and `_get_dose_total` compute the converted daily dose of
each prescribed drug and aggregate it per drug/day (and per kg of body
weight). They are pure functions over prescription rows, so they can be
exercised with lightweight stand-in objects and no database.
"""

import pytest

from services import alert_service

SPECIAL_FREQUENCIES = [33, 44, 55, 66, 99]


class _Drug:
    """Minimal stand-in for a PrescriptionDrug row."""

    def __init__(self, id_drug=1, frequency=2, dose=10, doseconv=None):
        self.idDrug = id_drug
        self.frequency = frequency
        self.dose = dose
        self.doseconv = doseconv


class _Attr:
    """Minimal stand-in for a DrugAttributes row (only 'division' is read)."""

    def __init__(self, division=None):
        self.division = division


class _Row:
    """Row-like object supporting both positional indexing and the
    ``measure_unit_convert_factor`` attribute, mirroring the SQLAlchemy Row
    that _get_dose_total consumes.

    Positions used by _get_dose_total: [0]=PrescriptionDrug, [6]=DrugAttributes,
    [10]=prescription_expire_date.
    """

    def __init__(self, prescription_drug, drug_attributes, expire_date, factor):
        self._cols = [None] * 11
        self._cols[0] = prescription_drug
        self._cols[6] = drug_attributes
        self._cols[10] = expire_date
        self.measure_unit_convert_factor = factor

    def __getitem__(self, index):
        return self._cols[index]


class _ExpireDate:
    """Stand-in for a datetime whose only read attribute is ``.day``."""

    def __init__(self, day):
        self.day = day


class TestGetDoseConv:
    """Tests for alert_service._get_dose_conv (single-item converted dose)."""

    def test_without_division_converts_the_dose_times_frequency(self):
        """When drug_attributes is None the converted dose is multiplied by frequency."""
        drug = _Drug(frequency=3, dose=5, doseconv=5)
        assert alert_service._get_dose_conv(drug, None, 1) == 15.0

    def test_without_division_converts_with_the_current_factor(self):
        """The stored doseconv is not used with a dose: prescalc stored 5 mg
        before the factor of 10 was registered, so the dose is converted now."""
        drug = _Drug(frequency=2, dose=5, doseconv=5)
        assert alert_service._get_dose_conv(drug, None, 10) == 100.0

    def test_with_division_uses_dose_factor_and_frequency(self):
        """With a division attribute the raw dose is scaled by factor and frequency."""
        drug = _Drug(frequency=2, dose=10)
        attr = _Attr(division=1)
        assert alert_service._get_dose_conv(drug, attr, 2) == 40.0

    def test_with_division_none_factor_defaults_to_one(self):
        """A None convert factor on the division branch defaults to 1."""
        drug = _Drug(frequency=2, dose=10)
        attr = _Attr(division=1)
        assert alert_service._get_dose_conv(drug, attr, None) == 20.0

    def test_division_none_converts_the_dose(self):
        """An attributes row whose division is None converts the dose too."""
        drug = _Drug(frequency=2, dose=10, doseconv=5)
        attr = _Attr(division=None)
        # dose (10) * factor (3) * frequency (2), the stored doseconv not read
        assert alert_service._get_dose_conv(drug, attr, 3) == 60.0

    @pytest.mark.parametrize("special", SPECIAL_FREQUENCIES)
    def test_special_frequencies_count_as_one(self, special):
        """Special frequency codes are treated as a frequency of 1."""
        drug = _Drug(frequency=special, dose=7)
        assert alert_service._get_dose_conv(drug, None, 1) == 7.0

    def test_no_dose_and_no_doseconv_is_zero(self):
        """Without a dose or a stored doseconv there is nothing to convert."""
        drug = _Drug(frequency=2, dose=None, doseconv=None)
        assert alert_service._get_dose_conv(drug, None, 1) == 0

    def test_differentiated_dose_uses_the_stored_daily_total(self):
        """Dose diferenciada: dose is 0 and prescalc summed the doses of the
        day into doseconv, already in the default unit (frequency 1)."""
        drug = _Drug(frequency=1, dose=0, doseconv=30)
        assert alert_service._get_dose_conv(drug, None, 1000) == 30.0

    def test_differentiated_dose_of_a_range_drug_is_zero(self):
        """A range drug's doseconv is rounded to the range, not a dose."""
        drug = _Drug(frequency=1, dose=0, doseconv=30)
        assert alert_service._get_dose_conv(drug, _Attr(division=10), 1) == 0


class TestGetDoseTotal:
    """Tests for alert_service._get_dose_total (per drug/day aggregation)."""

    def _row(self, drug, expire_day=5, attr=None, factor=1):
        return _Row(drug, attr, _ExpireDate(expire_day), factor)

    def test_single_drug_totals_and_per_kg(self):
        """A single row yields both an absolute total and a per-kg entry."""
        drug = _Drug(id_drug=1, frequency=2, dose=10)
        result = alert_service._get_dose_total([self._row(drug)], {"weight": 2})
        assert result["1_5"] == {"value": 20.0, "count": 1}
        # per kg: 20 / 2 = 10
        assert result["1_5kg"] == {"value": 10.0, "count": 1}

    def test_same_drug_same_day_accumulates(self):
        """Two rows of the same drug on the same day sum values and counts."""
        drug_a = _Drug(id_drug=1, frequency=1, dose=10)
        drug_b = _Drug(id_drug=1, frequency=1, dose=5)
        result = alert_service._get_dose_total(
            [self._row(drug_a), self._row(drug_b)], {"weight": 1}
        )
        assert result["1_5"] == {"value": 15.0, "count": 2}

    def test_different_expire_days_are_separate_buckets(self):
        """The same drug on different expiry days lands in distinct buckets."""
        drug = _Drug(id_drug=1, frequency=1, dose=10)
        result = alert_service._get_dose_total(
            [self._row(drug, expire_day=5), self._row(drug, expire_day=6)],
            {"weight": 1},
        )
        assert result["1_5"]["count"] == 1
        assert result["1_6"]["count"] == 1

    def test_frequency_66_is_excluded(self):
        """Frequency 66 (AGORA) rows are skipped entirely from the totals."""
        drug = _Drug(id_drug=1, frequency=66, dose=10)
        result = alert_service._get_dose_total([self._row(drug)], {"weight": 1})
        assert result == {}

    def test_missing_expire_date_uses_day_zero(self):
        """A row without an expiry date is bucketed under day 0."""
        drug = _Drug(id_drug=7, frequency=1, dose=4)
        row = _Row(drug, None, None, 1)
        result = alert_service._get_dose_total([row], {"weight": 1})
        assert "7_0" in result

    def test_zero_weight_defaults_to_one(self):
        """A non-positive weight is treated as 1 kg to avoid division by zero."""
        drug = _Drug(id_drug=1, frequency=1, dose=8)
        result = alert_service._get_dose_total([self._row(drug)], {"weight": 0})
        # value unchanged because weight defaults to 1
        assert result["1_5kg"]["value"] == 8.0

    def test_none_convert_factor_defaults_to_one(self):
        """A None measure-unit factor on a division drug defaults to 1."""
        drug = _Drug(id_drug=1, frequency=2, dose=10)
        attr = _Attr(division=1)
        result = alert_service._get_dose_total(
            [self._row(drug, attr=attr, factor=None)], {"weight": 1}
        )
        # dose (10) * factor (defaulted 1) * frequency (2) = 20
        assert result["1_5"]["value"] == 20.0

    def test_empty_drug_list_returns_empty_dict(self):
        """An empty drug list produces an empty aggregation."""
        assert alert_service._get_dose_total([], {"weight": 1}) == {}


class TestMaxDoseText:
    """The max dose alert texts print the dose without float noise."""

    def test_single_item_text(self):
        """0.1 * 3 is 0.30000000000000004 in float: the text says 0,30."""
        attributes = _Attr()
        attributes.useWeight = False
        attributes.maxDose = 0.2
        attributes.idMeasureUnit = "mg"
        alert = alert_service._alert_max_dose(
            prescription_drug=type(
                "PD", (), {"id": 1, "dose": 0.1, "frequency": 3, "doseconv": None}
            )(),
            drug_attributes=attributes,
            exams={"weight": 70},
            measure_unit_convert_factor=1,
        )
        assert "(0,30 mg)" in alert["text"]
        assert "(0,20 mg)" in alert["text"]
        assert "0.30000000000000004" not in alert["text"]

    def test_summed_text(self):
        """The summed (SOMADA) dose is printed the same way."""
        attributes = _Attr()
        attributes.useWeight = False
        attributes.maxDose = 0.2
        attributes.idMeasureUnit = "mg"
        alert = alert_service._alert_max_dose_total(
            prescription_drug=type("PD", (), {"id": 1, "idDrug": 7, "dose": 0.1})(),
            drug_attributes=attributes,
            exams={"weight": 70},
            prescription_expire_date=_ExpireDate(5),
            dose_total={"7_5": {"value": 0.1 + 0.2, "count": 2}},
        )
        assert "0,30 mg)" in alert["text"]
        assert "0.30000000000000004" not in alert["text"]

    def test_float_noise_does_not_fire_the_alert(self):
        """0.1 * 3 against a max dose of 0.3: equal, not greater (the product is
        0.30000000000000004 in float)."""
        attributes = _Attr()
        attributes.useWeight = False
        attributes.maxDose = 0.3
        attributes.idMeasureUnit = "mg"
        alert = alert_service._alert_max_dose(
            prescription_drug=type(
                "PD", (), {"id": 1, "dose": 0.1, "frequency": 3, "doseconv": None}
            )(),
            drug_attributes=attributes,
            exams={"weight": 70},
            measure_unit_convert_factor=1,
        )
        assert alert is None


class TestDoseTotalRounding:
    """The summed doses carry no float noise into the comparison."""

    def test_sum_is_rounded(self):
        """0.1 + 0.2 sums to 0.3, not 0.30000000000000004."""
        rows = [
            _Row(_Drug(id_drug=7, frequency=1, dose=0.1), _Attr(), _ExpireDate(5), 1),
            _Row(_Drug(id_drug=7, frequency=1, dose=0.2), _Attr(), _ExpireDate(5), 1),
        ]
        result = alert_service._get_dose_total(rows, {"weight": 1})
        assert result["7_5"]["value"] == 0.3
        assert result["7_5kg"]["value"] == 0.3
