"""Unit tests for prescription_drug_service._get_match_diff.

``_get_match_diff`` compares a ``checkedindex`` row (``r``) against the current
values of a ``PrescriptionDrug`` (``pd``) and returns the list of field names
that differ. An empty list means the checked snapshot still matches the drug.

The function is pure (no database access) and only reads attributes off the two
objects, so the row and the prescription drug are stand-ins built with
``SimpleNamespace``. Notable behaviors under test:

- ``notes`` is compared as an md5 hex digest (``complemento``);
- ``None`` solution fields are coalesced to ``0``;
- ``route`` coalesces ``None`` to an empty string;
- ``interval`` is truncated to its first 50 characters before comparison.
"""

import hashlib
from types import SimpleNamespace

from services import prescription_drug_service


def _md5(text: str) -> str:
    """Return the md5 hex digest the service uses to compare notes."""
    return hashlib.md5(text.encode()).hexdigest()


def _make_pd(**overrides):
    """Build a PrescriptionDrug-like object with sensible matching defaults."""
    pd = SimpleNamespace(
        doseconv=10.0,
        frequency=3,
        solutionPhase=1,
        solutionTime=2,
        solutionTotalTime=30,
        solutionDose=5,
        route="IV",
        interval="06:00 12:00 18:00",
        dose=100.0,
        notes="observacao",
    )
    for key, value in overrides.items():
        setattr(pd, key, value)
    return pd


def _make_matching_row(pd):
    """Build a checkedindex-like row that fully matches the given PrescriptionDrug."""
    return SimpleNamespace(
        doseconv=pd.doseconv,
        frequenciadia=pd.frequency,
        sletapas=(pd.solutionPhase or 0),
        slhorafase=(pd.solutionTime or 0),
        sltempoaplicacao=(pd.solutionTotalTime or 0),
        sldosagem=(pd.solutionDose or 0),
        via=(pd.route or ""),
        horario=(pd.interval[:50] if pd.interval else ""),
        dose=pd.dose,
        complemento=(_md5(pd.notes) if pd.notes else ""),
    )


class TestFullMatch:
    """Teste _get_match_diff - matching snapshots yield no differences"""

    def test_full_match_returns_empty_list(self):
        """A row equal to the drug on every field returns an empty diff."""
        pd = _make_pd()
        row = _make_matching_row(pd)
        assert prescription_drug_service._get_match_diff(row, pd) == []


class TestSingleFieldDifferences:
    """Teste _get_match_diff - a single differing field is reported"""

    def test_dose_difference(self):
        """A changed dose is reported."""
        pd = _make_pd()
        row = _make_matching_row(pd)
        row.dose = 999.0
        assert prescription_drug_service._get_match_diff(row, pd) == ["dose"]

    def test_doseconv_difference(self):
        """A changed converted dose is reported."""
        pd = _make_pd()
        row = _make_matching_row(pd)
        row.doseconv = 0.1
        assert prescription_drug_service._get_match_diff(row, pd) == ["doseconv"]

    def test_frequency_difference(self):
        """A changed daily frequency is reported under 'frequenciadia'."""
        pd = _make_pd()
        row = _make_matching_row(pd)
        row.frequenciadia = 99
        assert prescription_drug_service._get_match_diff(row, pd) == ["frequenciadia"]

    def test_route_difference(self):
        """A changed route is reported under 'via'."""
        pd = _make_pd()
        row = _make_matching_row(pd)
        row.via = "ORAL"
        assert prescription_drug_service._get_match_diff(row, pd) == ["via"]

    def test_interval_difference(self):
        """A changed schedule is reported under 'horario'."""
        pd = _make_pd()
        row = _make_matching_row(pd)
        row.horario = "23:00"
        assert prescription_drug_service._get_match_diff(row, pd) == ["horario"]


class TestNoneCoalescing:
    """Teste _get_match_diff - None solution/route fields coalesce to defaults"""

    def test_none_solution_fields_match_zero_row(self):
        """None solution fields on the drug match a row carrying 0."""
        pd = _make_pd(
            solutionPhase=None,
            solutionTime=None,
            solutionTotalTime=None,
            solutionDose=None,
        )
        row = _make_matching_row(pd)  # helper coalesces None -> 0
        # sanity: the row really is holding zeros for these fields
        assert row.sletapas == 0 and row.sldosagem == 0
        assert prescription_drug_service._get_match_diff(row, pd) == []

    def test_none_solution_field_differs_when_row_nonzero(self):
        """A None solution field differs from a non-zero row value."""
        pd = _make_pd(solutionPhase=None)
        row = _make_matching_row(pd)
        row.sletapas = 4
        assert prescription_drug_service._get_match_diff(row, pd) == ["sletapas"]

    def test_none_route_matches_empty_string_row(self):
        """A None route coalesces to '' and matches an empty-string row."""
        pd = _make_pd(route=None)
        row = _make_matching_row(pd)
        assert row.via == ""
        assert prescription_drug_service._get_match_diff(row, pd) == []


class TestNotesComplemento:
    """Teste _get_match_diff - notes compared as md5 'complemento'"""

    def test_matching_notes_digest(self):
        """A row whose complemento is the md5 of the notes matches."""
        pd = _make_pd(notes="alguma observacao")
        row = _make_matching_row(pd)
        assert row.complemento == _md5("alguma observacao")
        assert prescription_drug_service._get_match_diff(row, pd) == []

    def test_different_notes_digest_is_reported(self):
        """A stale complemento digest is reported."""
        pd = _make_pd(notes="nova observacao")
        row = _make_matching_row(pd)
        row.complemento = _md5("observacao antiga")
        assert prescription_drug_service._get_match_diff(row, pd) == ["complemento"]

    def test_empty_notes_match_empty_complemento(self):
        """When the drug has no notes, an empty complemento matches."""
        pd = _make_pd(notes=None)
        row = _make_matching_row(pd)
        assert row.complemento == ""
        assert prescription_drug_service._get_match_diff(row, pd) == []

    def test_none_complemento_row_treated_as_empty(self):
        """A None complemento on the row is coalesced to '' and matches empty notes."""
        pd = _make_pd(notes=None)
        row = _make_matching_row(pd)
        row.complemento = None
        assert prescription_drug_service._get_match_diff(row, pd) == []

    def test_notes_present_but_row_empty_is_reported(self):
        """Notes present on the drug but absent on the row is a difference."""
        pd = _make_pd(notes="observacao")
        row = _make_matching_row(pd)
        row.complemento = ""
        assert prescription_drug_service._get_match_diff(row, pd) == ["complemento"]


class TestIntervalTruncation:
    """Teste _get_match_diff - interval is truncated to 50 chars before comparing"""

    def test_only_first_50_chars_compared(self):
        """Intervals differing only beyond char 50 are treated as equal."""
        long_interval = "A" * 50 + "TAIL-THAT-IS-IGNORED"
        pd = _make_pd(interval=long_interval)
        row = _make_matching_row(pd)  # horario holds the 50-char prefix
        assert row.horario == "A" * 50
        assert prescription_drug_service._get_match_diff(row, pd) == []

    def test_difference_within_first_50_chars_is_reported(self):
        """A difference inside the first 50 chars is reported."""
        pd = _make_pd(interval="B" * 60)
        row = _make_matching_row(pd)
        row.horario = "C" * 50
        assert prescription_drug_service._get_match_diff(row, pd) == ["horario"]


class TestMultipleDifferences:
    """Teste _get_match_diff - multiple differing fields are all reported"""

    def test_reports_all_differing_fields_in_order(self):
        """Every differing field is returned, in the function's check order."""
        pd = _make_pd()
        row = _make_matching_row(pd)
        row.doseconv = -1
        row.via = "SC"
        row.dose = 0
        assert prescription_drug_service._get_match_diff(row, pd) == [
            "doseconv",
            "via",
            "dose",
        ]
