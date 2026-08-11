"""Unit tests for DrugList.sumAlerts (prescription alert-statistics aggregation).

``sumAlerts`` folds two independent alert sources into the ``alertStats`` summary
shown on the prescription header:

* ``relations`` — drug/drug interaction alerts, whose short codes are mapped to
  legacy keys (``it`` -> ``int``, ``dt``/``dm`` -> ``dup``, ...);
* ``alerts`` — clinical alerts (kidney/liver/platelets, max dose, ...).

It also derives a few composite fields (``dup`` legacy total, ``maxDose``,
``exams``) and escalates the overall severity ``level`` from the individual alert
levels. The method only reads ``self.relations``, ``self.alerts`` and mutates
``self.alertStats``, so the tests build a bare ``DrugList`` via ``__new__`` and
seed those attributes, avoiding the DB-heavy constructor.
"""

from utils.drug_list import DrugList


def _default_alert_stats():
    """A fresh copy of the alertStats structure DrugList.__init__ builds."""
    return {
        "dup": 0,
        "int": 0,
        "inc": 0,
        "rea": 0,
        "isl": 0,
        "maxTime": 0,
        "maxDose": 0,
        "kidney": 0,
        "liver": 0,
        "elderly": 0,
        "platelets": 0,
        "tube": 0,
        "exams": 0,
        "allergy": 0,
        "interactions": {},
        "total": 0,
        "level": "low",
    }


def _make_drug_list(relations_stats=None, relations_alerts=None, alerts_stats=None, alerts_alerts=None):
    """Build a DrugList with only the attributes sumAlerts reads."""
    instance = DrugList.__new__(DrugList)
    instance.alertStats = _default_alert_stats()
    instance.relations = {
        "stats": relations_stats or {},
        "alerts": relations_alerts or {},
    }
    instance.alerts = {
        "stats": alerts_stats or {},
        "alerts": alerts_alerts or {},
    }
    return instance


class TestSumAlertsEmpty:
    """Behaviour when there are no alerts at all."""

    def test_empty_sources_leave_defaults(self):
        """With no alerts the totals stay at zero and the level stays 'low'."""
        drug_list = _make_drug_list()
        drug_list.sumAlerts()
        assert drug_list.alertStats["total"] == 0
        assert drug_list.alertStats["maxDose"] == 0
        assert drug_list.alertStats["exams"] == 0
        assert drug_list.alertStats["level"] == "low"


class TestSumAlertsRelations:
    """Aggregation of drug/drug interaction (relations) statistics."""

    def test_maps_short_codes_to_legacy_keys(self):
        """Interaction short codes are copied to their legacy keys."""
        drug_list = _make_drug_list(relations_stats={"it": 2, "iy": 1, "sl": 4})
        drug_list.sumAlerts()
        assert drug_list.alertStats["int"] == 2
        assert drug_list.alertStats["inc"] == 1
        assert drug_list.alertStats["isl"] == 4

    def test_records_raw_codes_and_running_total(self):
        """Raw short codes are preserved under 'interactions' and summed into total."""
        drug_list = _make_drug_list(relations_stats={"it": 2, "iy": 1})
        drug_list.sumAlerts()
        assert drug_list.alertStats["interactions"] == {"it": 2, "iy": 1}
        assert drug_list.alertStats["total"] == 3

    def test_duplicate_legacy_total_combines_dm_and_dt(self):
        """When both duplicate codes are present, 'dup' is their combined count."""
        drug_list = _make_drug_list(relations_stats={"dm": 1, "dt": 3})
        drug_list.sumAlerts()
        assert drug_list.alertStats["dup"] == 4
        assert drug_list.alertStats["total"] == 4


class TestSumAlertsClinical:
    """Aggregation of clinical (alerts) statistics and composite fields."""

    def test_clinical_stats_are_copied_and_summed(self):
        """Each clinical stat is copied through and added to the running total."""
        drug_list = _make_drug_list(alerts_stats={"kidney": 1, "liver": 2, "tube": 3})
        drug_list.sumAlerts()
        assert drug_list.alertStats["kidney"] == 1
        assert drug_list.alertStats["liver"] == 2
        assert drug_list.alertStats["tube"] == 3
        assert drug_list.alertStats["total"] == 6

    def test_max_dose_combines_base_and_plus(self):
        """maxDose is the sum of the maxDose and maxDosePlus clinical counts."""
        drug_list = _make_drug_list(alerts_stats={"maxDose": 2, "maxDosePlus": 5})
        drug_list.sumAlerts()
        assert drug_list.alertStats["maxDose"] == 7

    def test_exams_is_composite_of_organ_alerts(self):
        """exams aggregates its own base plus kidney, liver and platelet alerts."""
        drug_list = _make_drug_list(
            alerts_stats={"exams": 1, "kidney": 2, "liver": 3, "platelets": 4}
        )
        drug_list.sumAlerts()
        assert drug_list.alertStats["exams"] == 10


class TestSumAlertsLevel:
    """Severity-level escalation from individual alert levels."""

    def test_medium_level_escalates_from_low(self):
        """A single medium alert escalates the overall level to medium."""
        drug_list = _make_drug_list(
            relations_alerts={"1": [{"level": "medium"}]}
        )
        drug_list.sumAlerts()
        assert drug_list.alertStats["level"] == "medium"

    def test_high_level_wins_over_medium(self):
        """A high alert takes precedence over medium alerts."""
        drug_list = _make_drug_list(
            relations_alerts={"1": [{"level": "medium"}]},
            alerts_alerts={"2": [{"level": "high"}]},
        )
        drug_list.sumAlerts()
        assert drug_list.alertStats["level"] == "high"

    def test_only_low_alerts_keep_level_low(self):
        """When every alert is low severity the overall level stays low."""
        drug_list = _make_drug_list(
            alerts_alerts={"1": [{"level": "low"}, {"level": "low"}]}
        )
        drug_list.sumAlerts()
        assert drug_list.alertStats["level"] == "low"
