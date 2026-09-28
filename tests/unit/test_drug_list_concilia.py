"""Unit tests for DrugList.conciliaList — the medication-reconciliation list.

When a pharmacist opens a conciliation prescription, the screen shows, beside
what the patient reported, the medication the patient is *already* on in the
hospital. ``DrugList.conciliaList`` builds that second list: it takes the rows
of the patient's current aggregated prescription
(``prescription_view_repository.find_drugs_by_prescription``) and flattens each
one into the entry the front end renders and the conciliation audit stores
(``prescription_view_service`` keeps it under ``conciliaList``, and the
substance inference in ``infer_substance_fuzzy`` matches against it).

The function had no coverage at all, yet it owns four decisions that silently
change what the pharmacist compares against:

* which rows qualify — a suspended drug is dropped, and only the drug,
  procedure and solution sources are listed (diets and materials are not);
* deduplication — two rows are the same entry only when the drug, the
  recommendation, the dose, the daily frequency *and* the schedule all match,
  so a dose change keeps both;
* the labels — the measure unit and the frequency come from their own tables
  when the join found them, and fall back to the raw id (or an empty string)
  when it did not, and a drug with no ``medicamento`` row is labelled
  ``Medicamento <id>``;
* the substance columns, which are what the fuzzy matcher later reads.

It is a static method over query rows, so no database or app context is
involved: the rows are real model instances wrapped in a named tuple that
mimics the columns the function reads off the query row.
"""

from collections import namedtuple
from datetime import datetime

import pytest

from models.appendix import Frequency, MeasureUnit
from models.enums import DrugTypeEnum
from models.main import Drug, Substance
from models.prescription import PrescriptionDrug
from utils.drug_list import DrugList

# The query behind conciliaList selects many more columns, but the function
# reads only these: the first four by position and the substance by name.
Row = namedtuple(
    "Row", ["PrescriptionDrug", "Drug", "MeasureUnit", "Frequency", "Substance"]
)


def _prescription_drug(
    id=1,
    id_prescription=10,
    id_drug=100,
    dose=500.0,
    frequency=2.0,
    interval="08:00 20:00",
    notes="tomar após a refeição",
    source=DrugTypeEnum.DRUG.value,
    suspended_date=None,
    id_measure_unit="1",
    id_frequency="2",
):
    """Build a PrescriptionDrug row with the fields conciliaList reads."""
    prescription_drug = PrescriptionDrug()
    prescription_drug.id = id
    prescription_drug.idPrescription = id_prescription
    prescription_drug.idDrug = id_drug
    prescription_drug.dose = dose
    prescription_drug.frequency = frequency
    prescription_drug.interval = interval
    prescription_drug.notes = notes
    prescription_drug.source = source
    prescription_drug.suspendedDate = suspended_date
    prescription_drug.idMeasureUnit = id_measure_unit
    prescription_drug.idFrequency = id_frequency

    return prescription_drug


def _drug(id=100, name="Dipirona"):
    """Build a Drug row."""
    drug = Drug()
    drug.id = id
    drug.name = name

    return drug


def _measure_unit(id="1", description="mg"):
    """Build a MeasureUnit row."""
    measure_unit = MeasureUnit()
    measure_unit.id = id
    measure_unit.description = description

    return measure_unit


def _frequency(id="2", description="12/12h"):
    """Build a Frequency row."""
    frequency = Frequency()
    frequency.id = id
    frequency.description = description

    return frequency


def _substance(id=1234, name="dipirona sódica", idclass="N02"):
    """Build a Substance row."""
    substance = Substance()
    substance.id = id
    substance.name = name
    substance.idclass = idclass

    return substance


# Tells an omitted column apart from one the outer join did not fill: passing
# ``None`` to _row means the row is genuinely absent.
_DEFAULT = object()


def _row(
    prescription_drug=_DEFAULT,
    drug=_DEFAULT,
    measure_unit=_DEFAULT,
    frequency=_DEFAULT,
    substance=_DEFAULT,
):
    """Wrap the model instances into the query row conciliaList consumes."""
    return Row(
        PrescriptionDrug=(
            _prescription_drug() if prescription_drug is _DEFAULT else prescription_drug
        ),
        Drug=_drug() if drug is _DEFAULT else drug,
        MeasureUnit=_measure_unit() if measure_unit is _DEFAULT else measure_unit,
        Frequency=_frequency() if frequency is _DEFAULT else frequency,
        Substance=_substance() if substance is _DEFAULT else substance,
    )


class TestConciliaListMapping:
    """The entry built for a row that qualifies."""

    def test_maps_every_field_of_a_prescription_drug(self):
        """A qualifying row becomes one entry carrying the whole prescription drug."""
        result = DrugList.conciliaList([_row()], [])

        assert len(result) == 1
        entry = result[0]

        # the ids the front end round-trips are strings
        assert entry["idPrescription"] == "10"
        assert entry["idPrescriptionDrug"] == "1"
        assert entry["idDrug"] == "100"
        assert entry["drug"] == "Dipirona"
        assert entry["dose"] == 500.0
        assert entry["frequencyday"] == 2.0
        assert entry["timeRaw"] == "08:00 20:00"
        assert entry["recommendation"] == "tomar após a refeição"

    def test_labels_the_measure_unit_and_the_frequency_from_their_own_rows(self):
        """The measure unit and the frequency are labelled from the joined rows."""
        entry = DrugList.conciliaList([_row()], [])[0]

        assert entry["measureUnit"] == {"value": "1", "label": "mg"}
        assert entry["frequency"] == {"value": "2", "label": "12/12h"}

    @pytest.mark.parametrize(
        ("interval", "formatted"),
        [
            # a plain hour count is spelled out
            ("8", "Às 8 Horas"),
            # a short list of hours becomes one readable sequence
            ("8 20", "às 8h, às 20h"),
            # anything that is not numeric is shown as it was prescribed
            ("08:00 20:00", "08:00 20:00"),
        ],
    )
    def test_keeps_the_raw_schedule_and_adds_a_readable_one(self, interval, formatted):
        """The schedule is kept as prescribed and a readable version is added beside it."""
        entry = DrugList.conciliaList(
            [_row(prescription_drug=_prescription_drug(interval=interval))], []
        )[0]

        assert entry["timeRaw"] == interval
        assert entry["time"] == formatted

    def test_copies_the_substance_columns(self):
        """The substance columns the fuzzy matcher reads are copied onto the entry."""
        entry = DrugList.conciliaList([_row()], [])[0]

        assert entry["sctid"] == "1234"
        assert entry["substance"] == "dipirona sódica"
        assert entry["idSubstanceClass"] == "N02"

    def test_a_row_without_a_substance_carries_empty_substance_columns(self):
        """A drug with no substance leaves the substance columns empty."""
        entry = DrugList.conciliaList([_row(substance=None)], [])[0]

        assert entry["sctid"] is None
        assert entry["substance"] is None
        assert entry["idSubstanceClass"] is None

    def test_a_drug_without_a_catalog_row_is_labelled_by_its_id(self):
        """A drug missing from the catalog is labelled 'Medicamento <id>'."""
        entry = DrugList.conciliaList([_row(drug=None)], [])[0]

        assert entry["drug"] == "Medicamento 100"

    def test_falls_back_to_the_raw_ids_when_the_lookup_rows_are_missing(self):
        """Without the lookup rows, the unit and frequency show their raw ids."""
        entry = DrugList.conciliaList(
            [_row(measure_unit=None, frequency=None)],
            [],
        )[0]

        assert entry["measureUnit"] == {"value": "1", "label": "1"}
        assert entry["frequency"] == {"value": "2", "label": "2"}

    def test_falls_back_to_an_empty_label_when_the_ids_are_missing_too(self):
        """A row with neither a lookup row nor an id shows an empty unit and frequency."""
        entry = DrugList.conciliaList(
            [
                _row(
                    prescription_drug=_prescription_drug(
                        id_measure_unit=None, id_frequency=None
                    ),
                    measure_unit=None,
                    frequency=None,
                )
            ],
            [],
        )[0]

        assert entry["measureUnit"] == {"value": "", "label": ""}
        assert entry["frequency"] == {"value": "", "label": ""}


class TestConciliaListFiltering:
    """Which rows make it into the list."""

    def test_a_suspended_drug_is_left_out(self):
        """A drug the prescriber suspended is not part of the current medication."""
        row = _row(
            prescription_drug=_prescription_drug(suspended_date=datetime(2024, 1, 1))
        )

        assert DrugList.conciliaList([row], []) == []

    @pytest.mark.parametrize(
        "source",
        [
            DrugTypeEnum.DRUG.value,
            DrugTypeEnum.PROCEDURE.value,
            DrugTypeEnum.SOLUTION.value,
        ],
    )
    def test_drugs_procedures_and_solutions_are_listed(self, source):
        """The three prescribable sources are all part of the list."""
        row = _row(prescription_drug=_prescription_drug(source=source))

        assert len(DrugList.conciliaList([row], [])) == 1

    @pytest.mark.parametrize(
        "source",
        [DrugTypeEnum.DIET.value, DrugTypeEnum.MATERIAL.value, None],
    )
    def test_other_sources_are_left_out(self, source):
        """Diets, materials and rows without a source are not medication."""
        row = _row(prescription_drug=_prescription_drug(source=source))

        assert DrugList.conciliaList([row], []) == []

    def test_an_empty_prescription_produces_an_empty_list(self):
        """A prescription with no drugs produces no entries."""
        assert DrugList.conciliaList([], []) == []


class TestConciliaListDeduplication:
    """Two rows collapse into one entry only when everything the list shows matches."""

    def test_identical_rows_collapse_into_one_entry(self):
        """The same drug prescribed twice identically is listed once."""
        rows = [_row(), _row(prescription_drug=_prescription_drug(id=2))]

        result = DrugList.conciliaList(rows, [])

        assert len(result) == 1
        # the first row wins, so the entry keeps its prescription drug id
        assert result[0]["idPrescriptionDrug"] == "1"

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("id_drug", 200),
            ("notes", "outra recomendação"),
            ("dose", 750.0),
            ("frequency", 3.0),
            ("interval", "06:00"),
        ],
    )
    def test_a_difference_in_what_is_shown_keeps_both_entries(self, field, value):
        """A row differing in any listed field is a separate entry."""
        rows = [
            _row(),
            _row(prescription_drug=_prescription_drug(id=2, **{field: value})),
        ]

        assert len(DrugList.conciliaList(rows, [])) == 2

    def test_a_difference_the_list_does_not_show_still_collapses(self):
        """Two rows differing only in a field the list ignores are one entry."""
        rows = [
            _row(),
            _row(prescription_drug=_prescription_drug(id=2, id_prescription=99)),
        ]

        assert len(DrugList.conciliaList(rows, [])) == 1

    def test_entries_are_appended_to_the_list_passed_in(self):
        """Rows are appended to the accumulator the caller provides."""
        already_listed = DrugList.conciliaList([_row()], [])

        result = DrugList.conciliaList(
            [_row(prescription_drug=_prescription_drug(id=2, id_drug=200))],
            already_listed,
        )

        assert result is already_listed
        assert [entry["idDrug"] for entry in result] == ["100", "200"]

    def test_an_entry_already_listed_is_not_appended_again(self):
        """A row matching an entry the accumulator already holds is skipped."""
        already_listed = DrugList.conciliaList([_row()], [])

        result = DrugList.conciliaList([_row()], already_listed)

        assert len(result) == 1
