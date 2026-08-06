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
