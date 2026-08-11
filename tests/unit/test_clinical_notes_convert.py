"""Unit tests for clinical_notes_service note-conversion helpers.

``convert_notes`` and ``convert_prescription_note`` shape database rows into
the dictionary format returned by the clinical-notes endpoints. They are pure
transforms: the only external dependency is ``feature_service.has_user_feature``
(the HIDE_NAMES flag), which is patched here so no request context, database or
network is required.

The two helpers must produce a compatible dict shape, mask the prescriber name
when HIDE_NAMES is on, gate the primary-care fields, truncate very long note
text, and project tag annotation counts onto both the tag name and its legacy
column alias.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from services import clinical_notes_service


def _patch_hide_names(value: bool):
    """Patch feature_service.has_user_feature (HIDE_NAMES) to the given value."""
    return patch.object(
        clinical_notes_service.feature_service,
        "has_user_feature",
        return_value=value,
    )


def _note(
    *,
    id=1,
    admission_number=555,
    text="a short note",
    form={"f": 1},
    template={"t": 2},
    date=datetime(2024, 1, 2, 3, 4, 5),
    prescriber="Dr. House",
    position="ENFERMARIA",
    annotations=None,
):
    """Build a ClinicalNotes-like row for convert_notes."""
    return SimpleNamespace(
        id=id,
        admissionNumber=admission_number,
        text=text,
        form=form,
        template=template,
        date=date,
        prescriber=prescriber,
        position=position,
        annotations=annotations,
    )


def _prescription_note(
    *,
    id=9,
    admission_number=777,
    text="prescription evolution",
    updatedAt=datetime(2024, 5, 6, 7, 8, 9),
    tpStatus="s",
    idPrescription=42,
):
    """Build a PrescriptionClinicalNote-like row for convert_prescription_note."""
    return SimpleNamespace(
        id=id,
        admission_number=admission_number,
        text=text,
        updatedAt=updatedAt,
        tpStatus=tpStatus,
        idPrescription=idPrescription,
    )


class TestConvertNotes:
    """Tests for clinical_notes_service.convert_notes."""

    def test_basic_shape_and_types(self):
        """The id is stringified and scalar fields are copied verbatim."""
        note = _note()
        with _patch_hide_names(False):
            result = clinical_notes_service.convert_notes(note, True, [])

        assert result["id"] == "1"
        assert result["id"] == str(note.id)
        assert result["admissionNumber"] == 555
        assert result["text"] == "a short note"
        assert result["date"] == "2024-01-02T03:04:05"
        assert result["position"] == "ENFERMARIA"

    def test_prescriber_shown_when_hide_names_off(self):
        """With HIDE_NAMES off the real prescriber name is returned."""
        with _patch_hide_names(False):
            result = clinical_notes_service.convert_notes(_note(), False, [])
        assert result["prescriber"] == "Dr. House"

    def test_prescriber_masked_when_hide_names_on(self):
        """With HIDE_NAMES on the prescriber name is masked."""
        with _patch_hide_names(True):
            result = clinical_notes_service.convert_notes(_note(), False, [])
        assert result["prescriber"] == "***"

    def test_primary_care_fields_included_when_enabled(self):
        """form/template are passed through when has_primary_care is True."""
        note = _note(form={"f": 1}, template={"t": 2})
        with _patch_hide_names(False):
            result = clinical_notes_service.convert_notes(note, True, [])
        assert result["form"] == {"f": 1}
        assert result["template"] == {"t": 2}

    def test_primary_care_fields_nulled_when_disabled(self):
        """form/template are None when has_primary_care is False."""
        note = _note(form={"f": 1}, template={"t": 2})
        with _patch_hide_names(False):
            result = clinical_notes_service.convert_notes(note, False, [])
        assert result["form"] is None
        assert result["template"] is None

    def test_short_text_is_not_truncated(self):
        """Text at or below the limit is returned unchanged."""
        note = _note(text="x" * 100)
        with _patch_hide_names(False):
            result = clinical_notes_service.convert_notes(note, False, [])
        assert result["text"] == "x" * 100

    def test_long_text_is_truncated_with_marker(self):
        """Text beyond 700000 chars is truncated and gets the cut marker."""
        note = _note(text="y" * 700_001)
        with _patch_hide_names(False):
            result = clinical_notes_service.convert_notes(note, False, [])
        assert result["text"].startswith("y" * 700_000)
        assert result["text"].endswith(
            "<p>Evolução cortada por texto muito longo.</p>"
        )
        assert len(result["text"]) == 700_000 + len(
            "<p>Evolução cortada por texto muito longo.</p>"
        )

    def test_none_text_stays_none(self):
        """A missing text is left as-is (the length guard is skipped)."""
        note = _note(text=None)
        with _patch_hide_names(False):
            result = clinical_notes_service.convert_notes(note, False, [])
        assert result["text"] is None

    def test_tag_count_from_annotations(self):
        """A tag maps to its ``<name>_count`` value in annotations."""
        note = _note(annotations={"dados_count": 3})
        tags = [{"name": "dados", "column": "info"}]
        with _patch_hide_names(False):
            result = clinical_notes_service.convert_notes(note, False, tags)
        assert result["dados"] == 3
        # legacy column alias mirrors the value
        assert result["info"] == 3

    def test_tag_defaults_to_zero_when_annotation_missing(self):
        """A tag with no matching annotation key defaults to zero."""
        note = _note(annotations={"other_count": 9})
        tags = [{"name": "dados", "column": "info"}]
        with _patch_hide_names(False):
            result = clinical_notes_service.convert_notes(note, False, tags)
        assert result["dados"] == 0
        assert result["info"] == 0

    def test_tag_defaults_to_zero_when_annotations_none(self):
        """A None annotations blob yields zero for every tag."""
        note = _note(annotations=None)
        tags = [{"name": "dados", "column": "info"}]
        with _patch_hide_names(False):
            result = clinical_notes_service.convert_notes(note, False, tags)
        assert result["dados"] == 0

    def test_tag_without_column_sets_only_name(self):
        """A tag with column=None sets the name key but no alias key."""
        note = _note(annotations={"acesso_count": 5})
        tags = [{"name": "acesso", "column": None}]
        with _patch_hide_names(False):
            result = clinical_notes_service.convert_notes(note, False, tags)
        assert result["acesso"] == 5
        assert None not in result


class TestConvertPrescriptionNote:
    """Tests for clinical_notes_service.convert_prescription_note."""

    def test_fixed_source_and_position(self):
        """Prescription notes carry a fixed source and position marker."""
        with _patch_hide_names(False):
            result = clinical_notes_service.convert_prescription_note(
                _prescription_note(), "Nurse Joy", []
            )
        assert result["source"] == "prescription"
        assert result["position"] == "EVOLUÇÃO CRIADA NA NOHARM"
        assert result["form"] is None
        assert result["template"] is None

    def test_scalar_fields_copied(self):
        """Identifier, status and prescription id are copied through."""
        note = _prescription_note(
            id=9, admission_number=777, tpStatus="s", idPrescription=42
        )
        with _patch_hide_names(False):
            result = clinical_notes_service.convert_prescription_note(
                note, "Nurse Joy", []
            )
        assert result["id"] == "9"
        assert result["admissionNumber"] == 777
        assert result["integrationStatus"] == "s"
        assert result["idPrescription"] == 42
        assert result["date"] == "2024-05-06T07:08:09"

    def test_creator_name_shown_when_hide_names_off(self):
        """With HIDE_NAMES off the creator name is used as prescriber."""
        with _patch_hide_names(False):
            result = clinical_notes_service.convert_prescription_note(
                _prescription_note(), "Nurse Joy", []
            )
        assert result["prescriber"] == "Nurse Joy"

    def test_missing_creator_name_becomes_empty_string(self):
        """A None creator name falls back to an empty string, not None."""
        with _patch_hide_names(False):
            result = clinical_notes_service.convert_prescription_note(
                _prescription_note(), None, []
            )
        assert result["prescriber"] == ""

    def test_creator_name_masked_when_hide_names_on(self):
        """With HIDE_NAMES on the creator name is masked."""
        with _patch_hide_names(True):
            result = clinical_notes_service.convert_prescription_note(
                _prescription_note(), "Nurse Joy", []
            )
        assert result["prescriber"] == "***"

    def test_tags_always_zero(self):
        """Prescription notes have no annotations, so every tag is zero."""
        tags = [
            {"name": "dados", "column": "info"},
            {"name": "acesso", "column": None},
        ]
        with _patch_hide_names(False):
            result = clinical_notes_service.convert_prescription_note(
                _prescription_note(), "Nurse Joy", tags
            )
        assert result["dados"] == 0
        assert result["info"] == 0
        assert result["acesso"] == 0

    def test_shares_core_keys_with_convert_notes(self):
        """The two converters agree on the shared core key set."""
        with _patch_hide_names(False):
            pn = clinical_notes_service.convert_prescription_note(
                _prescription_note(), "Nurse Joy", []
            )
            cn = clinical_notes_service.convert_notes(_note(), True, [])
        core_keys = {
            "id",
            "admissionNumber",
            "text",
            "form",
            "template",
            "date",
            "prescriber",
            "position",
        }
        assert core_keys.issubset(pn.keys())
        assert core_keys.issubset(cn.keys())
