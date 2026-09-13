"""Unit tests for the infusion/solution-dose helpers of utils.drug_list.DrugList.

These helpers power the Solution Calculator: ``get_solution_dose`` normalizes a
prescribed dose to millilitres (the unit total-volume math depends on), and
``getInfusionKey`` groups the items that make up a single solution/infusion.

The methods are pure with respect to the object's own attributes, so the tests
build a bare ``DrugList`` via ``__new__`` and set only the attributes each method
reads, avoiding the database/feature-flag work in ``DrugList.__init__``. The
prescription rows the methods consume are SQLAlchemy ``Row`` objects that support
both positional indexing (``pd[0]``) and attribute access (``pd.MeasureUnit``);
``_FakeRow`` reproduces just that dual interface.
"""

from datetime import datetime
from types import SimpleNamespace

from utils.drug_list import DrugList


class _FakeRow:
    """Minimal stand-in for a SQLAlchemy Row: positional + attribute access."""

    def __init__(self, items, **attrs):
        self._items = list(items)
        for key, value in attrs.items():
            setattr(self, key, value)

    def __getitem__(self, index):
        return self._items[index]


def _make_drug_list(is_cpoe=False):
    """Build a DrugList without running the DB-heavy constructor."""
    instance = DrugList.__new__(DrugList)
    instance.is_cpoe = is_cpoe
    return instance


def _solution_row(
    dose=0,
    doseconv=0,
    prescribed_unit=None,
    default_unit=None,
    division=False,
    default_convert_factor=None,
    solution_convert_factor=None,
):
    """Build a prescription row shaped like the ones get_solution_dose consumes.

    Index 0 carries the raw doses; index 6 carries drug attributes (dose ranges).
    The remaining positions are unused by the method but must exist so pd[6] is
    addressable.
    """
    prescription_drug = SimpleNamespace(dose=dose, doseconv=doseconv)
    drug_attributes = SimpleNamespace(division=division)
    measure_unit = (
        SimpleNamespace(measureunit_nh=prescribed_unit)
        if prescribed_unit is not None
        else None
    )
    items = [prescription_drug, None, None, None, None, None, drug_attributes]
    return _FakeRow(
        items,
        MeasureUnit=measure_unit,
        default_measure_unit_nh=default_unit,
        measure_unit_convert_factor=default_convert_factor,
        measure_unit_solution_convert_factor=solution_convert_factor,
    )


class TestGetSolutionDose:
    """Tests for DrugList.get_solution_dose (normalizes a dose to millilitres)."""

    def test_prescribed_unit_already_ml_returns_raw_dose(self):
        """When the item is prescribed in ml, its raw dose is returned as-is."""
        drug_list = _make_drug_list()
        row = _solution_row(dose=100, doseconv=5, prescribed_unit="ml")
        assert drug_list.get_solution_dose(row) == 100

    def test_default_unit_ml_returns_converted_dose(self):
        """When the default unit is ml, the pre-converted dose (doseconv) is used."""
        drug_list = _make_drug_list()
        row = _solution_row(dose=100, doseconv=50, prescribed_unit="mg", default_unit="ml")
        assert drug_list.get_solution_dose(row) == 50

    def test_missing_measure_unit_falls_back_to_default_unit(self):
        """A row without a measure unit still resolves via the default unit."""
        drug_list = _make_drug_list()
        row = _solution_row(dose=100, doseconv=30, prescribed_unit=None, default_unit="ml")
        assert drug_list.get_solution_dose(row) == 30

    def test_uses_solution_convert_factor_when_no_ml_unit(self):
        """With no ml unit, the converted dose is divided by the solution factor."""
        drug_list = _make_drug_list()
        row = _solution_row(
            doseconv=20,
            prescribed_unit="mg",
            default_unit="mg",
            solution_convert_factor=4,
        )
        assert drug_list.get_solution_dose(row) == 5.0

    def test_no_ml_unit_and_no_factor_returns_zero(self):
        """When conversion to ml is impossible, the dose is reported as 0."""
        drug_list = _make_drug_list()
        row = _solution_row(
            doseconv=20,
            prescribed_unit="mg",
            default_unit="mg",
            solution_convert_factor=None,
        )
        assert drug_list.get_solution_dose(row) == 0

    def test_dose_ranges_recompute_conversion_from_raw_dose(self):
        """With dose ranges, doseconv is recomputed from dose * default factor."""
        drug_list = _make_drug_list()
        row = _solution_row(
            dose=10,
            doseconv=999,  # ignored: dose ranges force a recompute
            prescribed_unit="mg",
            default_unit="ml",
            division=True,
            default_convert_factor=2,
        )
        assert drug_list.get_solution_dose(row) == 20

    def test_dose_ranges_without_factor_yield_zero(self):
        """Dose ranges with no default convert factor collapse the dose to 0."""
        drug_list = _make_drug_list()
        row = _solution_row(
            dose=10,
            doseconv=999,
            prescribed_unit="mg",
            default_unit="mg",
            division=True,
            default_convert_factor=None,
        )
        assert drug_list.get_solution_dose(row) == 0

    def test_dose_ranges_then_solution_factor(self):
        """Dose ranges recompute the dose, then the solution factor scales it."""
        drug_list = _make_drug_list()
        row = _solution_row(
            dose=10,
            prescribed_unit="mg",
            default_unit="mg",
            division=True,
            default_convert_factor=3,  # doseconv := 10 * 3 = 30
            solution_convert_factor=6,  # 30 / 6 = 5
        )
        assert drug_list.get_solution_dose(row) == 5.0


class TestGetInfusionKey:
    """Tests for DrugList.getInfusionKey (groups items of one solution)."""

    def test_non_cpoe_concatenates_prescription_and_solution_group(self):
        """Outside CPOE the key is prescription id concatenated with solution group."""
        drug_list = _make_drug_list(is_cpoe=False)
        row = _FakeRow([SimpleNamespace(idPrescription=10, solutionGroup=3)])
        assert drug_list.getInfusionKey(row) == "103"

    def test_cpoe_prefers_cpoe_group(self):
        """In CPOE mode the cpoe_group, when present, is the grouping key."""
        drug_list = _make_drug_list(is_cpoe=True)
        row = _FakeRow([SimpleNamespace(cpoe_group="G1", solutionGroup=3)])
        assert drug_list.getInfusionKey(row) == "G1"

    def test_cpoe_falls_back_to_solution_group(self):
        """In CPOE mode without a cpoe_group the solution group is used instead."""
        drug_list = _make_drug_list(is_cpoe=True)
        row = _FakeRow([SimpleNamespace(cpoe_group=None, solutionGroup=3)])
        assert drug_list.getInfusionKey(row) == 3


def _infusion_row(
    id=1000,
    solution_group=1,
    cpoe_group=None,
    id_prescription=10,
    dose=0,
    doseconv=0,
    prescribed_unit=None,
    default_unit=None,
    solution_convert_factor=None,
    amount=None,
    amount_unit=None,
    measure_unit_id=None,
    solution_dose=None,
    solution_unit=None,
    suspended_date=None,
):
    """Build a prescription row shaped like the ones getInfusionList consumes.

    Index 0 is the presmed row, index 2 the prescribed measure unit (whose ``id``
    is compared against the drug amount unit) and index 6 the drug attributes
    (``amount``/``amountUnit`` describe the solution concentration).
    """
    prescription_drug = SimpleNamespace(
        id=id,
        idPrescription=id_prescription,
        solutionGroup=solution_group,
        cpoe_group=cpoe_group,
        dose=dose,
        doseconv=doseconv,
        solutionDose=solution_dose,
        solutionUnit=solution_unit,
        suspendedDate=suspended_date,
    )
    drug_attributes = SimpleNamespace(
        division=False, amount=amount, amountUnit=amount_unit
    )
    measure_unit = (
        SimpleNamespace(id=measure_unit_id) if measure_unit_id is not None else None
    )
    items = [prescription_drug, None, measure_unit, None, None, None, drug_attributes]
    return _FakeRow(
        items,
        MeasureUnit=SimpleNamespace(measureunit_nh=prescribed_unit)
        if prescribed_unit is not None
        else None,
        default_measure_unit_nh=default_unit,
        measure_unit_convert_factor=None,
        measure_unit_solution_convert_factor=solution_convert_factor,
    )


def _make_drug_list_with(rows, is_cpoe=False):
    """Build a DrugList holding the given rows, bypassing the DB-heavy constructor."""
    drug_list = _make_drug_list(is_cpoe=is_cpoe)
    drug_list.drugList = rows
    return drug_list


class TestGetInfusionList:
    """Tests for DrugList.getInfusionList (total volume per solution group)."""

    def test_items_outside_a_solution_are_ignored(self):
        """Rows with neither a solution group nor a cpoe group are not aggregated."""
        drug_list = _make_drug_list_with(
            [_infusion_row(solution_group=None, cpoe_group=None, dose=50)]
        )
        assert drug_list.getInfusionList() == {}

    def test_single_item_totals_its_own_volume(self):
        """A lone solution item defines the group's total volume and concentration."""
        drug_list = _make_drug_list_with(
            [
                _infusion_row(
                    dose=250,
                    prescribed_unit="ml",
                    amount=5,
                    amount_unit="mg",
                    measure_unit_id="ml",
                )
            ]
        )

        result = drug_list.getInfusionList()

        assert list(result.keys()) == ["101"]
        assert result["101"]["totalVol"] == 250
        assert result["101"]["vol"] == 250
        assert result["101"]["amount"] == 5
        assert result["101"]["unit"] == "mg"
        assert result["101"]["disableTotal"] is False

    def test_total_volume_sums_every_item_of_the_group(self):
        """Every item of a solution adds its own volume to the group total."""
        drug_list = _make_drug_list_with(
            [
                _infusion_row(id=1001, dose=100.005, prescribed_unit="ml"),
                _infusion_row(id=1002, dose=50, prescribed_unit="ml"),
            ]
        )

        # 150.005 keeps three decimals: the running total is rounded, not truncated
        assert drug_list.getInfusionList()["101"]["totalVol"] == 150.005

    def test_items_of_different_groups_are_kept_apart(self):
        """Each solution group gets its own entry, keyed by prescription and group."""
        drug_list = _make_drug_list_with(
            [
                _infusion_row(
                    id=1001, solution_group=1, dose=100, prescribed_unit="ml"
                ),
                _infusion_row(id=1002, solution_group=2, dose=30, prescribed_unit="ml"),
            ]
        )

        result = drug_list.getInfusionList()

        assert result["101"]["totalVol"] == 100
        assert result["102"]["totalVol"] == 30

    def test_cpoe_groups_are_keyed_by_cpoe_group(self):
        """In CPOE mode the items are grouped by the cpoe group instead."""
        drug_list = _make_drug_list_with(
            [
                _infusion_row(id=1001, cpoe_group="G1", dose=100, prescribed_unit="ml"),
                _infusion_row(id=1002, cpoe_group="G1", dose=20, prescribed_unit="ml"),
            ],
            is_cpoe=True,
        )

        assert drug_list.getInfusionList()["G1"]["totalVol"] == 120

    def test_suspended_items_do_not_change_the_totals(self):
        """A suspended item keeps the group visible but adds nothing to it."""
        drug_list = _make_drug_list_with(
            [
                _infusion_row(
                    id=1001,
                    dose=80,
                    prescribed_unit="ml",
                    suspended_date=datetime(2025, 1, 1),
                ),
                _infusion_row(id=1002, dose=20, prescribed_unit="ml"),
            ]
        )

        assert drug_list.getInfusionList()["101"]["totalVol"] == 20

    def test_unconvertible_dose_disables_the_total(self):
        """An item whose dose cannot be converted to ml flags the group total as unusable."""
        drug_list = _make_drug_list_with(
            [
                _infusion_row(
                    id=1001, dose=10, prescribed_unit="mg", default_unit="mg"
                ),
                _infusion_row(id=1002, dose=90, prescribed_unit="ml"),
            ]
        )

        result = drug_list.getInfusionList()

        assert result["101"]["disableTotal"] is True
        assert result["101"]["totalVol"] == 90

    def test_main_component_overrides_an_earlier_item(self):
        """The "000" item is the solution's main component and wins over earlier ones."""
        drug_list = _make_drug_list_with(
            [
                _infusion_row(
                    id=1001,
                    dose=40,
                    prescribed_unit="ml",
                    amount=2,
                    amount_unit="mg",
                    solution_dose=10,
                    solution_unit="ml/h",
                ),
                _infusion_row(
                    id=1000,
                    dose=60,
                    prescribed_unit="ml",
                    amount=7,
                    amount_unit="g",
                    solution_dose=33,
                    solution_unit="mcg/kg/min",
                ),
            ]
        )

        result = drug_list.getInfusionList()

        assert result["101"]["vol"] == 60
        assert result["101"]["amount"] == 7
        assert result["101"]["unit"] == "g"
        assert result["101"]["speed"] == 33
        assert result["101"]["speedUnit"] == "mcg/kg/min"
        assert result["101"]["totalVol"] == 100

    def test_later_items_do_not_override_the_main_component(self):
        """Once the "000" item has set the concentration, later items leave it alone."""
        drug_list = _make_drug_list_with(
            [
                _infusion_row(
                    id=1000,
                    dose=60,
                    prescribed_unit="ml",
                    amount=7,
                    amount_unit="g",
                    solution_dose=33,
                    solution_unit="mcg/kg/min",
                ),
                _infusion_row(
                    id=1001,
                    dose=40,
                    prescribed_unit="ml",
                    amount=2,
                    amount_unit="mg",
                    solution_dose=10,
                    solution_unit="ml/h",
                ),
            ]
        )

        result = drug_list.getInfusionList()

        assert result["101"]["vol"] == 60
        assert result["101"]["amount"] == 7
        assert result["101"]["unit"] == "g"
        assert result["101"]["speed"] == 33
        assert result["101"]["speedUnit"] == "mcg/kg/min"
        assert result["101"]["totalVol"] == 100

    def test_dose_prescribed_in_the_amount_unit_is_recalculated(self):
        """When the dose is prescribed in the concentration unit, volume is dose/amount."""
        drug_list = _make_drug_list_with(
            [
                _infusion_row(
                    dose=30,
                    doseconv=30,
                    default_unit="ml",
                    amount=4,
                    amount_unit="mg",
                    measure_unit_id="MG",
                )
            ]
        )

        result = drug_list.getInfusionList()

        # 30 mg of a 4 mg/ml solution = 7.5 ml, used for both the item and the total
        assert result["101"]["vol"] == 7.5
        assert result["101"]["totalVol"] == 7.5

    def test_amount_without_unit_is_taken_as_the_volume(self):
        """An amount with no unit describes the item volume directly."""
        drug_list = _make_drug_list_with(
            [_infusion_row(dose=999, prescribed_unit="ml", amount=15, amount_unit=None)]
        )

        result = drug_list.getInfusionList()

        assert result["101"]["vol"] == 15
        assert result["101"]["totalVol"] == 15

    def test_speed_is_read_from_the_solution_dose(self):
        """The infusion speed and its unit come from the solution dose fields."""
        drug_list = _make_drug_list_with(
            [
                _infusion_row(
                    dose=100,
                    prescribed_unit="ml",
                    solution_dose=42.5,
                    solution_unit="ml/h",
                )
            ]
        )

        result = drug_list.getInfusionList()

        assert result["101"]["speed"] == 42.5
        assert result["101"]["speedUnit"] == "ml/h"
