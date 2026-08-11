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

    def __init__(self, id_drug=1, frequency=2, dose=10, doseconv=5):
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

    def test_without_division_uses_doseconv_times_frequency(self):
        """When drug_attributes is None the pre-converted dose is multiplied by frequency."""
        drug = _Drug(frequency=3, doseconv=5)
        assert alert_service._get_dose_conv(drug, None, 1) == 15.0

    def test_without_division_ignores_convert_factor(self):
        """The measure-unit factor is not applied on the doseconv branch."""
        drug = _Drug(frequency=2, doseconv=5)
        # factor of 10 is ignored because there is no division attribute
        assert alert_service._get_dose_conv(drug, None, 10) == 10.0

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

    def test_division_none_falls_back_to_doseconv_branch(self):
        """An attributes row whose division is None uses the doseconv branch."""
        drug = _Drug(frequency=2, dose=10, doseconv=5)
        attr = _Attr(division=None)
        # doseconv (5) * frequency (2) = 10, dose/factor path not taken
        assert alert_service._get_dose_conv(drug, attr, 99) == 10.0

    @pytest.mark.parametrize("special", SPECIAL_FREQUENCIES)
    def test_special_frequencies_count_as_one(self, special):
        """Special frequency codes are treated as a frequency of 1."""
        drug = _Drug(frequency=special, doseconv=7)
        assert alert_service._get_dose_conv(drug, None, 1) == 7.0

    def test_non_numeric_doseconv_is_zeroed(self):
        """A non-numeric dose value is coerced to zero (via none2zero)."""
        drug = _Drug(frequency=2, doseconv=None)
        assert alert_service._get_dose_conv(drug, None, 1) == 0


class TestGetDoseTotal:
    """Tests for alert_service._get_dose_total (per drug/day aggregation)."""

    def _row(self, drug, expire_day=5, attr=None, factor=1):
        return _Row(drug, attr, _ExpireDate(expire_day), factor)

    def test_single_drug_totals_and_per_kg(self):
        """A single row yields both an absolute total and a per-kg entry."""
        drug = _Drug(id_drug=1, frequency=2, doseconv=10)
        result = alert_service._get_dose_total([self._row(drug)], {"weight": 2})
        assert result["1_5"] == {"value": 20.0, "count": 1}
        # per kg: 20 / 2 = 10
        assert result["1_5kg"] == {"value": 10.0, "count": 1}

    def test_same_drug_same_day_accumulates(self):
        """Two rows of the same drug on the same day sum values and counts."""
        drug_a = _Drug(id_drug=1, frequency=1, doseconv=10)
        drug_b = _Drug(id_drug=1, frequency=1, doseconv=5)
        result = alert_service._get_dose_total(
            [self._row(drug_a), self._row(drug_b)], {"weight": 1}
        )
        assert result["1_5"] == {"value": 15.0, "count": 2}

    def test_different_expire_days_are_separate_buckets(self):
        """The same drug on different expiry days lands in distinct buckets."""
        drug = _Drug(id_drug=1, frequency=1, doseconv=10)
        result = alert_service._get_dose_total(
            [self._row(drug, expire_day=5), self._row(drug, expire_day=6)],
            {"weight": 1},
        )
        assert result["1_5"]["count"] == 1
        assert result["1_6"]["count"] == 1

    def test_frequency_66_is_excluded(self):
        """Frequency 66 (AGORA) rows are skipped entirely from the totals."""
        drug = _Drug(id_drug=1, frequency=66, doseconv=10)
        result = alert_service._get_dose_total([self._row(drug)], {"weight": 1})
        assert result == {}

    def test_missing_expire_date_uses_day_zero(self):
        """A row without an expiry date is bucketed under day 0."""
        drug = _Drug(id_drug=7, frequency=1, doseconv=4)
        row = _Row(drug, None, None, 1)
        result = alert_service._get_dose_total([row], {"weight": 1})
        assert "7_0" in result

    def test_zero_weight_defaults_to_one(self):
        """A non-positive weight is treated as 1 kg to avoid division by zero."""
        drug = _Drug(id_drug=1, frequency=1, doseconv=8)
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
