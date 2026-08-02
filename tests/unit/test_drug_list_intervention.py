"""Unit tests for utils.drug_list.DrugList intervention-matching and helper methods.

These methods carry the pharmacist-facing logic that links a prescription drug to
prior clinical interventions and normalizes drug/schedule data for the prescription
view. They are pure with respect to the object's own attributes, so the tests build a
bare ``DrugList`` via ``__new__`` and set only the attributes each method reads,
avoiding the heavy database/feature-flag work in ``DrugList.__init__``.
"""

from datetime import datetime

from utils.drug_list import DrugList


def _make_drug_list(interventions=None, drug_results=None, admission_number=111):
    """Build a DrugList without running the DB-heavy constructor.

    Only the attributes exercised by the methods under test are populated.
    """
    instance = DrugList.__new__(DrugList)
    instance.admission_number = admission_number
    instance.interventions = interventions if interventions is not None else []
    instance.drug_results = drug_results if drug_results is not None else []
    return instance


def _intervention(
    id_intervention,
    id_drug=10,
    status="s",
    id_prescription="50",
    admission_number=111,
):
    """Build an intervention record shaped like the ones DrugList consumes."""
    return {
        "id": id_intervention,
        "idDrug": id_drug,
        "status": status,
        "idPrescription": id_prescription,
        "admissionNumber": admission_number,
    }


class TestGetPrevIntervention:
    """Tests for DrugList.getPrevIntervention (most recent accepted prior intervention)."""

    def test_no_interventions_returns_empty_dict(self):
        """With no interventions the result is an empty dict."""
        drug_list = _make_drug_list()
        assert drug_list.getPrevIntervention(idDrug=10, idPrescription=100) == {}

    def test_matches_accepted_prior_intervention(self):
        """An accepted ('s') intervention on the same drug/admission is returned."""
        drug_list = _make_drug_list(interventions=[_intervention(1)])
        result = drug_list.getPrevIntervention(idDrug=10, idPrescription=100)
        assert result["id"] == 1

    def test_ignores_non_accepted_status(self):
        """Interventions whose status is not 's' are ignored."""
        drug_list = _make_drug_list(interventions=[_intervention(1, status="0")])
        assert drug_list.getPrevIntervention(idDrug=10, idPrescription=100) == {}

    def test_ignores_other_drug(self):
        """Interventions for a different drug are ignored."""
        drug_list = _make_drug_list(interventions=[_intervention(1, id_drug=99)])
        assert drug_list.getPrevIntervention(idDrug=10, idPrescription=100) == {}

    def test_ignores_other_admission(self):
        """Interventions from a different admission are ignored."""
        drug_list = _make_drug_list(
            interventions=[_intervention(1, admission_number=222)]
        )
        assert drug_list.getPrevIntervention(idDrug=10, idPrescription=100) == {}

    def test_ignores_same_or_later_prescription(self):
        """Only interventions on an earlier prescription qualify."""
        drug_list = _make_drug_list(
            interventions=[_intervention(1, id_prescription="100")]
        )
        assert drug_list.getPrevIntervention(idDrug=10, idPrescription=100) == {}

    def test_returns_highest_id_among_matches(self):
        """When several match, the one with the highest id wins."""
        drug_list = _make_drug_list(
            interventions=[
                _intervention(1, id_prescription="50"),
                _intervention(5, id_prescription="60"),
                _intervention(3, id_prescription="40"),
            ]
        )
        result = drug_list.getPrevIntervention(idDrug=10, idPrescription=100)
        assert result["id"] == 5


class TestGetExistIntervention:
    """Tests for DrugList.getExistIntervention (any prior intervention exists)."""

    def test_true_for_any_prior_intervention_regardless_of_status(self):
        """A prior intervention on the same drug/admission counts even if not accepted."""
        drug_list = _make_drug_list(interventions=[_intervention(1, status="0")])
        assert drug_list.getExistIntervention(idDrug=10, idPrescription=100) is True

    def test_false_without_earlier_prescription(self):
        """No earlier prescription means no prior intervention exists."""
        drug_list = _make_drug_list(
            interventions=[_intervention(1, id_prescription="50")]
        )
        assert drug_list.getExistIntervention(idDrug=10, idPrescription=40) is False

    def test_false_for_other_admission(self):
        """A prior intervention from another admission does not count."""
        drug_list = _make_drug_list(
            interventions=[_intervention(1, admission_number=222)]
        )
        assert drug_list.getExistIntervention(idDrug=10, idPrescription=100) is False


class TestGetIntervention:
    """Tests for DrugList.getIntervention (lookup by prescription-drug id)."""

    def test_returns_matching_intervention(self):
        """The intervention whose id matches the prescription-drug id is returned."""
        drug_list = _make_drug_list(
            interventions=[_intervention(5), _intervention(7)]
        )
        assert drug_list.getIntervention(5)["id"] == 5

    def test_no_match_returns_empty_dict(self):
        """A missing id yields an empty dict."""
        drug_list = _make_drug_list(interventions=[_intervention(5)])
        assert drug_list.getIntervention(999) == {}


class TestGetDrugsBySource:
    """Tests for DrugList.get_drugs_by_source (filter processed drugs by source)."""

    def test_filters_by_requested_sources(self):
        """Only drugs whose source is in the requested list are returned."""
        drug_list = _make_drug_list(
            drug_results=[
                {"source": "Medicamentos"},
                {"source": "Dietas"},
                {"source": "Soluções"},
            ]
        )
        result = drug_list.get_drugs_by_source(["Medicamentos", "Dietas"])
        assert [d["source"] for d in result] == ["Medicamentos", "Dietas"]

    def test_no_match_returns_empty_list(self):
        """No matching source yields an empty list."""
        drug_list = _make_drug_list(drug_results=[{"source": "Medicamentos"}])
        assert drug_list.get_drugs_by_source(["Procedimentos"]) == []


class TestSortDrugs:
    """Tests for DrugList.sortDrugs (accent-insensitive drug sort key)."""

    def test_returns_lowercased_accent_stripped_key(self):
        """The key is the accent-stripped, lowercased drug name (bytes)."""
        assert DrugList.sortDrugs({"drug": "Ácido"}) == b"acido"

    def test_orders_names_accent_insensitively(self):
        """Sorting by the key orders names ignoring accents and case."""
        drugs = [{"drug": "Zinco"}, {"drug": "Ácido"}, {"drug": "bromo"}]
        ordered = [d["drug"] for d in sorted(drugs, key=DrugList.sortDrugs)]
        assert ordered == ["Ácido", "bromo", "Zinco"]


class TestCpoeDrugs:
    """Tests for DrugList.cpoeDrugs (rewrite ids for CPOE prescriptions)."""

    def test_moves_prescription_id_into_cpoe(self):
        """The original idPrescription is preserved under 'cpoe' and replaced."""
        drugs = [{"idPrescription": 20, "name": "x"}]
        result = DrugList.cpoeDrugs(drugs, idPrescription=99)
        assert result[0]["cpoe"] == 20
        assert result[0]["idPrescription"] == 99

    def test_rewrites_every_drug(self):
        """Every drug in the list gets the shared prescription id."""
        drugs = [{"idPrescription": 20}, {"idPrescription": 30}]
        result = DrugList.cpoeDrugs(drugs, idPrescription=99)
        assert [d["idPrescription"] for d in result] == [99, 99]
        assert [d["cpoe"] for d in result] == [20, 30]


class TestScheduleToArray:
    """Tests for DrugList.schedule_to_array (serialize a schedule to sorted iso pairs)."""

    def test_empty_schedule_returns_empty_list(self):
        """A falsy schedule returns an empty list."""
        assert DrugList.schedule_to_array(None) == []
        assert DrugList.schedule_to_array([]) == []

    def test_serializes_and_sorts_descending(self):
        """Datetime pairs become iso strings ordered most-recent first."""
        schedule = [
            (datetime(2024, 1, 1, 8, 0), datetime(2024, 1, 1, 9, 0)),
            (datetime(2024, 1, 2, 8, 0), datetime(2024, 1, 2, 9, 0)),
        ]
        result = DrugList.schedule_to_array(schedule)
        assert result == [
            ["2024-01-02T08:00:00", "2024-01-02T09:00:00"],
            ["2024-01-01T08:00:00", "2024-01-01T09:00:00"],
        ]

    def test_limits_to_ten_entries(self):
        """No more than ten schedule entries are returned."""
        schedule = [
            (datetime(2024, 1, day, 8, 0), datetime(2024, 1, day, 9, 0))
            for day in range(1, 16)
        ]
        result = DrugList.schedule_to_array(schedule)
        assert len(result) == 10
        # The most recent day (15) is kept, the oldest (day 1) is dropped.
        assert result[0][0] == "2024-01-15T08:00:00"
