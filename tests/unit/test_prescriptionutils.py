"""Unit tests for utils.prescriptionutils prescription helper functions."""

from datetime import datetime, timedelta

import pytest

from utils import prescriptionutils


class TestLenghStay:
    """Tests for prescriptionutils.lenghStay (length of hospital stay in days)."""

    def test_none_admission_returns_empty_string(self):
        """A missing admission date returns an empty string."""
        assert prescriptionutils.lenghStay(None, None) == ""

    def test_open_stay_uses_today(self):
        """Without a discharge date the stay is measured up to today."""
        admission = datetime.today() - timedelta(days=10)
        assert prescriptionutils.lenghStay(admission, None) == 10

    def test_closed_stay(self):
        """With a discharge date the stay is the span between the two dates."""
        admission = datetime(2024, 1, 1)
        discharge = datetime(2024, 1, 6)
        assert prescriptionutils.lenghStay(admission, discharge) == 5

    def test_negative_stay_clamped_to_zero(self):
        """A discharge earlier than admission is clamped to zero."""
        admission = datetime(2024, 1, 10)
        discharge = datetime(2024, 1, 1)
        assert prescriptionutils.lenghStay(admission, discharge) == 0


class TestTimeValue:
    """Tests for prescriptionutils.timeValue (human readable time labels)."""

    def test_single_time(self):
        """A single numeric time is rendered as a full 'Às N Horas' label."""
        assert prescriptionutils.timeValue("8") == "Às 8 Horas"

    def test_multiple_times(self):
        """Multiple space-separated times below the cap are joined with 'h' markers."""
        assert prescriptionutils.timeValue("8 14") == "às 8h, às 14h"

    def test_six_or_more_times_returned_unchanged(self):
        """Six or more times are returned unchanged."""
        value = "8 10 12 14 16 18"
        assert prescriptionutils.timeValue(value) == value

    def test_non_numeric_returned_stripped(self):
        """A non-numeric value is returned trimmed of surrounding whitespace."""
        assert prescriptionutils.timeValue("  SN  ") == "SN"


class TestFreqValue:
    """Tests for prescriptionutils.freqValue (special frequency codes)."""

    @pytest.mark.parametrize(
        "code, label",
        [
            (33, "SN"),
            (44, "ACM"),
            (55, "CONT"),
            (66, "AGORA"),
            (99, "N/D"),
        ],
    )
    def test_special_codes(self, code, label):
        """Known special frequency codes map to their labels."""
        assert prescriptionutils.freqValue(code) == label

    def test_regular_frequency_returned_unchanged(self):
        """An ordinary frequency value is returned unchanged."""
        assert prescriptionutils.freqValue(8) == 8


class TestInteractionsList:
    """Tests for prescriptionutils.interactionsList."""

    def test_splits_name_and_id(self):
        """Each entry is split into its name and drug id components."""
        result = prescriptionutils.interactionsList(
            ["Aspirina|123", "Dipirona|456"], "|"
        )
        assert result == [
            {"name": "Aspirina", "idDrug": "123"},
            {"name": "Dipirona", "idDrug": "456"},
        ]

    def test_empty_list(self):
        """An empty input list yields an empty result."""
        assert prescriptionutils.interactionsList([], "|") == []


class TestGetNumericDrugAttributesList:
    """Tests for prescriptionutils.get_numeric_drug_attributes_list."""

    def test_contains_expected_attributes(self):
        """The list exposes the known numeric drug attribute keys."""
        attributes = prescriptionutils.get_numeric_drug_attributes_list()
        assert "antimicro" in attributes
        assert "controlled" in attributes
        assert "chemo" in attributes

    def test_returns_unique_values(self):
        """The attribute list has no duplicates."""
        attributes = prescriptionutils.get_numeric_drug_attributes_list()
        assert len(attributes) == len(set(attributes))


class TestSplitInterval:
    """Tests for prescriptionutils.split_interval."""

    def test_none_returns_empty_list(self):
        """None input returns an empty list."""
        assert prescriptionutils.split_interval(None) == []

    def test_empty_string_returns_empty_list(self):
        """An empty string returns an empty list."""
        assert prescriptionutils.split_interval("") == []

    def test_times_with_minutes_keep_hour_only(self):
        """Tokens with a ':' keep only the hour part."""
        assert prescriptionutils.split_interval("06:00 12:00 18:30") == [
            "06",
            "12",
            "18",
        ]

    def test_plain_hours_preserved(self):
        """Plain hour tokens are preserved."""
        assert prescriptionutils.split_interval("8 12 18") == ["8", "12", "18"]

    def test_extra_spaces_ignored(self):
        """Empty tokens produced by extra spaces are ignored."""
        assert prescriptionutils.split_interval("06:00  12:00") == ["06", "12"]


class TestGenAggId:
    """Tests for prescriptionutils.gen_agg_id (aggregated prescription id)."""

    @pytest.mark.parametrize(
        "admission_number, id_segment, pdate",
        [
            (None, 1, datetime(2024, 3, 15)),
            (42, None, datetime(2024, 3, 15)),
            (42, 1, None),
        ],
    )
    def test_missing_argument_returns_none(self, admission_number, id_segment, pdate):
        """Any missing argument produces a None id."""
        assert prescriptionutils.gen_agg_id(admission_number, id_segment, pdate) is None

    def test_encodes_date_segment_and_admission(self):
        """The id packs year, month, day, segment and admission number."""
        result = prescriptionutils.gen_agg_id(42, 1, datetime(2024, 3, 15))
        assert result == 2403151000000042

    def test_different_days_produce_different_ids(self):
        """Distinct prescription dates produce distinct ids."""
        day1 = prescriptionutils.gen_agg_id(42, 1, datetime(2024, 3, 15))
        day2 = prescriptionutils.gen_agg_id(42, 1, datetime(2024, 3, 16))
        assert day1 != day2


class TestGetPrescriptionItemPeriod:
    """Tests for prescriptionutils.get_prescription_item_period."""

    def test_cpoe_with_previous_period(self):
        """CPOE items with a previous period sum the cpoe and item periods."""
        period, total = prescriptionutils.get_prescription_item_period(
            is_cpoe=True, item_period=2, cpoe_period=3
        )
        assert period == "D3"
        assert total == 5.0

    def test_cpoe_without_previous_period(self):
        """CPOE items without a previous period add one to the cpoe period."""
        period, total = prescriptionutils.get_prescription_item_period(
            is_cpoe=True, item_period=None, cpoe_period=3
        )
        assert period == "D3"
        assert total == 4.0

    def test_cpoe_without_cpoe_period(self):
        """CPOE items without a cpoe period yield an empty label and total of 1."""
        period, total = prescriptionutils.get_prescription_item_period(
            is_cpoe=True, item_period=0, cpoe_period=None
        )
        assert period == ""
        assert total == 1

    def test_non_cpoe_total_period(self):
        """Non-CPOE items report the item period as the total."""
        _, total = prescriptionutils.get_prescription_item_period(
            is_cpoe=False, item_period=5, cpoe_period=None
        )
        assert total == 5.0


class TestSortRelations:
    """Tests for prescriptionutils.sortRelations (drug interaction sort key)."""

    def test_returns_accent_stripped_key(self):
        """The sort key is the accent-stripped 'nameB' field."""
        # remove_accents returns bytes, so the key is an ascii byte string.
        assert prescriptionutils.sortRelations({"nameB": "Ácido"}) == b"Acido"

    def test_orders_relations_by_name_b(self):
        """Relations are ordered by their accent-insensitive 'nameB'."""
        relations = [{"nameB": "Zinco"}, {"nameB": "Ácido"}, {"nameB": "Bromo"}]
        ordered = sorted(relations, key=prescriptionutils.sortRelations)
        assert [r["nameB"] for r in ordered] == ["Ácido", "Bromo", "Zinco"]


class TestGetInternalPrescriptionIds:
    """Tests for prescriptionutils.get_internal_prescription_ids."""

    def test_collects_ids_across_sources(self):
        """Ids are gathered from prescription, solution and procedures."""
        result = {
            "prescription": [{"idPrescription": 10}],
            "solution": [{"idPrescription": 20}],
            "procedures": [{"idPrescription": 30}],
        }
        assert sorted(prescriptionutils.get_internal_prescription_ids(result)) == [
            10,
            20,
            30,
        ]

    def test_cpoe_id_takes_precedence(self):
        """When a 'cpoe' attribute is present it is used instead of idPrescription."""
        result = {
            "prescription": [{"cpoe": 20, "idPrescription": 99}],
            "solution": [],
            "procedures": [],
        }
        assert prescriptionutils.get_internal_prescription_ids(result) == [20]

    def test_ids_are_deduplicated(self):
        """Repeated ids across sources are returned only once."""
        result = {
            "prescription": [{"idPrescription": 10}, {"idPrescription": 10}],
            "solution": [{"idPrescription": 10}],
            "procedures": [],
        }
        assert prescriptionutils.get_internal_prescription_ids(result) == [10]


def _make_drug(**overrides):
    """Build a prescription-drug dict with the fields getFeatures reads."""
    drug = {
        "idDrug": 1,
        "idSubstance": None,
        "idSubstanceClass": None,
        "whiteList": False,
        "suspended": False,
        "allergy": 0,
        "alertsComplete": [],
        "score": "0",
        "am": 0,
        "av": 0,
        "np": 0,
        "c": 0,
        "checked": True,
        "tubeAlert": 0,
        "frequency": {"value": ""},
        "idDepartment": 10,
        "interval": None,
    }
    drug.update(overrides)
    return drug


def _make_result(**overrides):
    """Build the aggregated prescription result dict getFeatures expects."""
    result = {
        "prescription": [],
        "solution": [],
        "procedures": [],
        "interventions": [],
        "alertExams": 0,
        "complication": 0,
    }
    result.update(overrides)
    return result


class TestGetFeatures:
    """Tests for prescriptionutils.getFeatures (prescription feature aggregation)."""

    def test_empty_prescription_is_all_zero(self):
        """An empty prescription produces zeroed counters and a low alert level."""
        features = prescriptionutils.getFeatures(_make_result())
        assert features["totalItens"] == 0
        assert features["prescriptionScore"] == 0
        assert features["globalScore"] == 0
        assert features["alertLevel"] == "low"
        assert features["drugIDs"] == []

    def test_counts_scores_and_flags(self):
        """Per-drug scores, flags and unchecked counts are aggregated."""
        drug_high = _make_drug(
            score="2",
            am=1,
            av=1,
            allergy=1,
            checked=False,
            tubeAlert=1,
            alertsComplete=[{"level": "high"}],
        )
        drug_three = _make_drug(idDrug=2, score="3", np=1, c=1)
        features = prescriptionutils.getFeatures(
            _make_result(
                prescription=[drug_high, drug_three],
                alertExams=2,
                interventions=[{"status": "s"}, {"status": "x"}],
            )
        )
        assert features["scoreTwo"] == 1
        assert features["scoreThree"] == 1
        assert features["prescriptionScore"] == 5
        assert features["am"] == 1
        assert features["av"] == 1
        assert features["np"] == 1
        assert features["controlled"] == 1
        assert features["allergy"] == 1
        assert features["alergy"] == 1  # legacy misspelled alias
        assert features["diff"] == 1  # one unchecked item
        assert features["tube"] == 1
        assert features["alertLevel"] == "high"
        assert features["interventions"] == 1  # only status 's' counts
        # globalScore = pScore + av + am + exams + alerts + diff
        assert features["globalScore"] == 5 + 1 + 1 + 2 + 1 + 1

    def test_deduplicates_ids_and_collects_metadata(self):
        """Drug/substance ids are de-duplicated and intervals/frequencies gathered."""
        drug_a = _make_drug(
            idDrug=1,
            idSubstance=100,
            idSubstanceClass=5,
            interval="08:00 20:00",
            frequency={"value": "12"},
            idDepartment=3,
        )
        drug_b = _make_drug(
            idDrug=1,
            idSubstance=100,
            frequency={"value": "8"},
            idDepartment=4,
        )
        features = prescriptionutils.getFeatures(
            _make_result(prescription=[drug_a, drug_b])
        )
        assert sorted(features["drugIDs"]) == [1]
        assert features["substanceIDs"] == [100]
        assert features["substanceClassIDs"] == [5]
        assert features["intervals"] == ["08", "20"]
        assert sorted(features["frequencies"]) == ["12", "8"]
        assert sorted(features["departmentList"]) == [3, 4]

    def test_whitelisted_drug_skips_scoring_but_counts_attributes(self):
        """A whitelisted drug is excluded from scores yet still feeds ids/attributes."""
        whitelisted = _make_drug(
            idDrug=9,
            whiteList=True,
            score="5",
            am=1,
            idDepartment=99,
            drugAttributes={"antimicro": 2},
        )
        features = prescriptionutils.getFeatures(
            _make_result(prescription=[whitelisted])
        )
        # excluded from score/flag aggregation...
        assert features["prescriptionScore"] == 0
        assert features["am"] == 0
        assert 99 not in features["departmentList"]
        # ...but still contributes to id lists and attribute totals.
        assert features["drugIDs"] == [9]
        assert features["drugAttributes"]["antimicro"] == 2
        assert features["totalItens"] == 1

    def test_collects_inner_prescription_dates(self):
        """Inner prescription dates are de-duplicated and sorted, even for
        whitelisted/suspended items, and missing dates are ignored."""
        later = _make_drug(idDrug=1, prescriptionDate="2026-09-02T14:00:00")
        earlier = _make_drug(idDrug=2, prescriptionDate="2026-09-01T08:00:00")
        duplicate = _make_drug(
            idDrug=3, whiteList=True, prescriptionDate="2026-09-02T14:00:00"
        )
        suspended = _make_drug(
            idDrug=4, suspended=True, prescriptionDate="2026-09-02T20:00:00"
        )
        no_date = _make_drug(idDrug=5, prescriptionDate=None)
        legacy = _make_drug(idDrug=6)  # header calls may not carry the key

        features = prescriptionutils.getFeatures(
            _make_result(
                prescription=[later, earlier, duplicate],
                solution=[suspended],
                procedures=[no_date, legacy],
            )
        )
        assert features["prescriptionDates"] == [
            "2026-09-01T08:00:00",
            "2026-09-02T14:00:00",
            "2026-09-02T20:00:00",
        ]

    def test_prescription_dates_empty_when_absent(self):
        """A prescription without inner dates yields an empty list."""
        features = prescriptionutils.getFeatures(_make_result())
        assert features["prescriptionDates"] == []

    def test_agg_path_uses_alert_stats(self):
        """When alertStats is present it drives the alert total and level."""
        drug = _make_drug(alertsComplete=[{"level": "high"}])
        features = prescriptionutils.getFeatures(
            _make_result(
                prescription=[drug],
                alertStats={"total": 7, "level": "medium"},
                protocolAlerts={"summary": [1, 2]},
            )
        )
        # alerts = alertStats total (7) + protocol summary length (2)
        assert features["alerts"] == 9
        assert features["alertLevel"] == "medium"
        assert features["protocolAlerts"] == [1, 2]
        assert features["alertStats"] == {"total": 7, "level": "medium"}
