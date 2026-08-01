"""Unit tests for the pure/static helpers of utils.drug_list.DrugList.

These cover medication-reconciliation (conciliation) helpers and small
list-normalization utilities that do not require a database or app context,
so they can be exercised directly as static methods.
"""

from datetime import datetime

from utils.drug_list import DrugList, _get_legacy_alert


class TestGetLegacyAlert:
    """Tests for _get_legacy_alert (maps alert kinds to legacy keys)."""

    def test_known_kinds_map_to_legacy_keys(self):
        """Each known alert kind maps to its legacy identifier."""
        assert _get_legacy_alert("it") == "int"
        assert _get_legacy_alert("dt") == "dup"
        assert _get_legacy_alert("dm") == "dup"
        assert _get_legacy_alert("iy") == "inc"
        assert _get_legacy_alert("sl") == "isl"
        assert _get_legacy_alert("rx") == "rea"


class TestSortDrugs:
    """Tests for DrugList.sortDrugs (accent-insensitive sort key)."""

    def test_returns_lowercased_ascii_key(self):
        """The sort key strips accents and lowercases the drug name."""
        # remove_accents returns bytes, so the key is a lowercased byte string.
        assert DrugList.sortDrugs({"drug": "Ácido Fólico"}) == b"acido folico"

    def test_orders_accented_names_naturally(self):
        """Accented names sort alongside their unaccented equivalents."""
        drugs = [{"drug": "Zinco"}, {"drug": "Água"}, {"drug": "Bromo"}]
        ordered = sorted(drugs, key=DrugList.sortDrugs)
        assert [d["drug"] for d in ordered] == ["Água", "Bromo", "Zinco"]


class TestChangeDrugName:
    """Tests for DrugList.changeDrugName (patient free-text drug relabeling)."""

    def test_zero_id_drug_uses_time_as_name(self):
        """A drug with idDrug '0' has its name replaced by its time field."""
        result = DrugList.changeDrugName([{"idDrug": "0", "drug": "x", "time": "08:00"}])
        assert result[0]["drug"] == "08:00"

    def test_regular_drug_name_unchanged(self):
        """A drug with a real idDrug keeps its original name."""
        result = DrugList.changeDrugName(
            [{"idDrug": "9", "drug": "Dipirona", "time": "y"}]
        )
        assert result[0]["drug"] == "Dipirona"

    def test_returns_all_items(self):
        """Every input item is present in the output."""
        result = DrugList.changeDrugName(
            [
                {"idDrug": "0", "drug": "a", "time": "06:00"},
                {"idDrug": "1", "drug": "b", "time": "c"},
            ]
        )
        assert len(result) == 2
        assert result[0]["drug"] == "06:00"
        assert result[1]["drug"] == "b"


class TestCpoeDrugs:
    """Tests for DrugList.cpoeDrugs (rewrites prescription id for CPOE view)."""

    def test_moves_original_id_into_cpoe_and_sets_new_id(self):
        """The original idPrescription is preserved under 'cpoe' and replaced."""
        result = DrugList.cpoeDrugs(
            [{"idPrescription": "10"}, {"idPrescription": "11"}], "99"
        )
        assert result == [
            {"idPrescription": "99", "cpoe": "10"},
            {"idPrescription": "99", "cpoe": "11"},
        ]

    def test_empty_list(self):
        """An empty drug list yields an empty result."""
        assert DrugList.cpoeDrugs([], "99") == []


class TestScheduleToArray:
    """Tests for DrugList.schedule_to_array (schedule tuples to iso pairs)."""

    def test_none_returns_empty_list(self):
        """A missing schedule returns an empty list."""
        assert DrugList.schedule_to_array(None) == []

    def test_empty_returns_empty_list(self):
        """An empty schedule returns an empty list."""
        assert DrugList.schedule_to_array([]) == []

    def test_formats_and_sorts_descending(self):
        """Entries are converted to iso pairs and sorted newest-first."""
        schedule = [
            (datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 9)),
            (datetime(2024, 1, 2, 8), datetime(2024, 1, 2, 9)),
        ]
        result = DrugList.schedule_to_array(schedule)
        assert result == [
            ["2024-01-02T08:00:00", "2024-01-02T09:00:00"],
            ["2024-01-01T08:00:00", "2024-01-01T09:00:00"],
        ]

    def test_limits_to_ten_entries(self):
        """No more than ten entries are returned."""
        schedule = [(datetime(2024, 1, 1, h), datetime(2024, 1, 1, h)) for h in range(15)]
        result = DrugList.schedule_to_array(schedule)
        assert len(result) == 10


class TestInferSubstanceFuzzy:
    """Tests for DrugList.infer_substance_fuzzy (fuzzy medication matching)."""

    def test_non_zero_id_copies_substance_id(self):
        """A drug that already has an id copies its idSubstance to sctid_infer."""
        concilia = [{"idDrug": "5", "drug": "Something", "idSubstance": 77}]
        result = DrugList.infer_substance_fuzzy(concilia, [], 0.7)
        assert result[0]["sctid_infer"] == "77"

    def test_non_zero_id_without_substance_sets_none(self):
        """A drug with an id but no substance gets a None sctid_infer."""
        concilia = [{"idDrug": "5", "drug": "Something"}]
        result = DrugList.infer_substance_fuzzy(concilia, [], 0.7)
        assert result[0]["sctid_infer"] is None

    def test_matches_by_drug_name(self):
        """A free-text drug is matched to a prescription drug by name."""
        concilia = [{"idDrug": "0", "drug": "Dipirona 500mg"}]
        prescription = [
            {"drug": "DIPIRONA", "substance": "metamizol", "sctid": "111"},
            {"drug": "PARACETAMOL", "substance": "acetaminofeno", "sctid": "222"},
        ]
        result = DrugList.infer_substance_fuzzy(concilia, prescription, 0.7)
        assert result[0]["sctid_infer"] == "111"
        assert result[0]["matched_drug"] == "DIPIRONA"
        assert result[0]["match_score"] == 1.0

    def test_matches_by_substance_name(self):
        """A free-text drug can be matched against the substance name."""
        concilia = [{"idDrug": "0", "drug": "Metamizol"}]
        prescription = [
            {"drug": "DIPIRONA", "substance": "METAMIZOL", "sctid": "111"},
        ]
        result = DrugList.infer_substance_fuzzy(concilia, prescription, 0.7)
        assert result[0]["sctid_infer"] == "111"

    def test_no_match_below_threshold_leaves_drug_untouched(self):
        """When nothing clears the threshold, no inference keys are added."""
        concilia = [{"idDrug": "0", "drug": "CompletelyUnknownXYZ"}]
        prescription = [{"drug": "DIPIRONA", "substance": "metamizol", "sctid": "111"}]
        result = DrugList.infer_substance_fuzzy(concilia, prescription, 0.7)
        assert "sctid_infer" not in result[0]
        assert "matched_drug" not in result[0]

    def test_drug_without_name_is_skipped(self):
        """An entry without a drug name is left unchanged."""
        concilia = [{"idDrug": "0", "drug": ""}]
        prescription = [{"drug": "DIPIRONA", "substance": "metamizol", "sctid": "111"}]
        result = DrugList.infer_substance_fuzzy(concilia, prescription, 0.7)
        assert "sctid_infer" not in result[0]

    def test_threshold_is_respected(self):
        """A very high threshold rejects an otherwise-plausible partial match."""
        concilia = [{"idDrug": "0", "drug": "Dipirona Sodica"}]
        prescription = [{"drug": "DIPIRONA", "substance": None, "sctid": "111"}]
        strict = DrugList.infer_substance_fuzzy(
            [dict(c) for c in concilia], prescription, 0.99
        )
        lenient = DrugList.infer_substance_fuzzy(
            [dict(c) for c in concilia], prescription, 0.3
        )
        assert "sctid_infer" not in strict[0]
        assert lenient[0]["sctid_infer"] == "111"
