"""Unit tests for the clinical-note PDF renderer.

``clinical_notes_pdf_service`` turns a clinical note into the PDF that gets
sent to ODOO for digital signature. Two shapes of note reach it: the free-text
note (HTML) and the primary-care custom form (a ``template`` describing groups
of questions plus a ``form`` holding the answers). Both are flattened into
``(text, bold)`` runs so the emphasis of the original note survives into the
document.

The renderer also decides where the signature field lands: ``build_note_pdf``
returns the page number and the vertical position (as a fraction of the A4
height) right where the body ended, and the sign service feeds those straight
to ODOO — a wrong value puts the signature on top of the text.

These are unit tests: ``db`` is replaced with a mock session for the
institution-header lookup, and the produced PDF is inspected as bytes.
"""

from unittest import mock

import pytest

from models.appendix import Memory
from models.notes import ClinicalNotes
from services import clinical_notes_pdf_service
from services.clinical_notes_pdf_service import (
    _format_form_value,
    _get_institution_header_runs,
    _get_note_runs,
    _runs_to_markdown,
    _to_latin1,
    build_note_pdf,
)


def _note(text=None, template=None, form=None):
    """Build a transient ClinicalNotes row with only the printable columns set."""
    note = ClinicalNotes()
    note.id = 1
    note.admissionNumber = 1
    note.text = text
    note.template = template
    note.form = form
    return note


def _mock_db(header=None):
    """A mock ``db`` whose Memory lookup returns the given nav-header record."""
    mock_db = mock.MagicMock()
    memory = None

    if header is not None:
        memory = Memory()
        memory.kind = "nav-header"
        memory.value = {"header": header}

    mock_db.session.query.return_value.filter.return_value.first.return_value = memory

    return mock_db


# --------------------------------------------------------------------------
# _to_latin1
# --------------------------------------------------------------------------


def test_latin1_keeps_accented_characters():
    """Portuguese accents are inside latin-1, so they must survive untouched"""
    assert _to_latin1("Avaliação diária não concluída") == (
        "Avaliação diária não concluída"
    )


def test_latin1_replaces_unsupported_characters():
    """Characters outside latin-1 are replaced instead of raising"""
    result = _to_latin1("dose 10 mg — ok ✓")

    assert "?" in result
    # the replacement is per character, so the surrounding text is preserved
    assert result.startswith("dose 10")
    assert result.endswith("ok ?")


def test_latin1_of_none_is_empty():
    """A note without text must not blow up the renderer"""
    assert _to_latin1(None) == ""


# --------------------------------------------------------------------------
# _runs_to_markdown
# --------------------------------------------------------------------------


def test_runs_to_markdown_wraps_only_the_bold_runs():
    """Bold runs get FPDF's markdown markers; plain runs are emitted as-is"""
    assert _runs_to_markdown([("Hospital ", False), ("Central", True)]) == (
        "Hospital **Central**"
    )


def test_runs_to_markdown_escapes_markers_present_in_the_text():
    """Marker sequences in the source text are printed, not interpreted"""
    for marker in ("**", "__", "~~", "--"):
        assert _runs_to_markdown([(f"a{marker}b", False)]) == f"a\\{marker}b"


def test_runs_to_markdown_escapes_markers_inside_a_bold_run():
    """Escaping happens before the bold wrapping, so both survive"""
    assert _runs_to_markdown([("x--y", True)]) == "**x\\--y**"


def test_runs_to_markdown_of_no_runs_is_empty():
    """An empty header must not produce a stray marker"""
    assert _runs_to_markdown([]) == ""


# --------------------------------------------------------------------------
# _format_form_value
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, ""])
def test_form_value_without_an_answer_is_labeled(value):
    """An unanswered question is printed as "Sem resposta", like the frontend"""
    assert _format_form_value(value) == "Sem resposta"


def test_form_value_list_is_joined():
    """Multiple-choice answers are joined with a comma"""
    assert _format_form_value(["Dor", "Febre"]) == "Dor, Febre"


def test_form_value_list_of_numbers_is_stringified():
    """A numeric multiple-choice answer is coerced before joining"""
    assert _format_form_value([1, 2]) == "1, 2"


def test_form_value_dict_uses_the_label():
    """A select answer carries {value,label}: the label is what gets printed"""
    assert _format_form_value({"value": 3, "label": "Moderado"}) == "Moderado"


def test_form_value_dict_without_a_label_is_empty():
    """A malformed select answer prints nothing instead of its raw dict"""
    assert _format_form_value({"value": 3}) == ""


def test_form_value_scalar_is_stringified():
    """Numbers and booleans are printed as text"""
    assert _format_form_value(72) == "72"
    assert _format_form_value(False) == "False"


def test_form_value_zero_is_printed_not_treated_as_missing():
    """0 is a real answer: the "no answer" check must not swallow it"""
    assert _format_form_value(0) == "0"


# --------------------------------------------------------------------------
# _get_note_runs — free text
# --------------------------------------------------------------------------


def test_note_runs_convert_the_free_text_html():
    """A free-text note is rendered from its HTML, keeping the emphasis"""
    runs = _get_note_runs(_note(text="<p>Paciente <b>estável</b></p>"))

    assert runs == [("Paciente ", False), ("estável", True)]


def test_note_runs_prefer_the_text_over_the_template():
    """A note holding both columns is a free-text note: the form is ignored"""
    runs = _get_note_runs(
        _note(
            text="<p>texto livre</p>",
            template=[{"group": "G", "questions": [{"id": "1", "label": "L"}]}],
            form={"1": "valor"},
        )
    )

    assert runs == [("texto livre", False)]


def test_note_runs_of_an_empty_note_are_empty():
    """A note with neither text nor template renders an empty body"""
    assert _get_note_runs(_note()) == []


# --------------------------------------------------------------------------
# _get_note_runs — custom form
# --------------------------------------------------------------------------


def test_note_runs_render_a_single_group_without_its_name():
    """One group carries no grouping information, so its name is omitted"""
    note = _note(
        template=[
            {
                "group": "Anamnese",
                "questions": [
                    {"id": "q1", "label": "Queixa"},
                    {"id": "q2", "label": "Duração"},
                ],
            }
        ],
        form={"q1": "Dor de cabeça", "q2": "3 dias"},
    )

    text = "".join([run for run, _ in _get_note_runs(note)])

    assert "Anamnese" not in text
    assert "Queixa: Dor de cabeça" in text
    assert "Duração: 3 dias" in text


def test_note_runs_print_the_group_names_when_there_is_more_than_one():
    """With several groups the names are the only way to read the form"""
    note = _note(
        template=[
            {"group": "Anamnese", "questions": [{"id": "q1", "label": "Queixa"}]},
            {"group": "Exame físico", "questions": [{"id": "q2", "label": "PA"}]},
        ],
        form={"q1": "Dor", "q2": "120/80"},
    )

    text = "".join([run for run, _ in _get_note_runs(note)])

    assert "Anamnese" in text
    assert "Exame físico" in text
    assert text.index("Anamnese") < text.index("Exame físico")


def test_note_runs_skip_an_unnamed_group():
    """A group without a name contributes only its questions"""
    note = _note(
        template=[
            {"group": "", "questions": [{"id": "q1", "label": "Queixa"}]},
            {"group": "Exame físico", "questions": [{"id": "q2", "label": "PA"}]},
        ],
        form={"q1": "Dor", "q2": "120/80"},
    )

    text = "".join([run for run, _ in _get_note_runs(note)])

    assert text.startswith("Queixa: Dor")
    assert "Exame físico" in text


def test_note_runs_omit_the_prefix_of_an_unlabeled_question():
    """Free letters have no label: printing "': '" would be noise"""
    note = _note(
        template=[
            {
                "group": "Conduta",
                "questions": [
                    {"id": "q1", "label": ""},
                    {"id": "q2", "label": "Retorno"},
                ],
            }
        ],
        form={"q1": "Mantida a conduta", "q2": "30 dias"},
    )

    text = "".join([run for run, _ in _get_note_runs(note)])

    assert text.startswith("Mantida a conduta")
    assert ": Mantida" not in text
    assert "Retorno: 30 dias" in text


def test_note_runs_label_the_unanswered_questions():
    """A question missing from the answers is printed as unanswered"""
    note = _note(
        template=[
            {
                "group": "Anamnese",
                "questions": [
                    {"id": "q1", "label": "Queixa"},
                    {"id": "q2", "label": "Duração"},
                ],
            }
        ],
        form={"q1": "Dor"},
    )

    text = "".join([run for run, _ in _get_note_runs(note)])

    assert "Duração: Sem resposta" in text


def test_note_runs_convert_the_html_of_a_form_answer():
    """Answers are HTML too, so the emphasis inside them is preserved"""
    note = _note(
        template=[{"group": "Conduta", "questions": [{"id": "q1", "label": "Plano"}]}],
        form={"q1": "manter <b>jejum</b>"},
    )

    runs = _get_note_runs(note)

    assert ("jejum", True) in runs


def test_note_runs_of_a_form_are_normalized():
    """normalize_runs trims the body and collapses the group separators"""
    note = _note(
        template=[{"group": "Conduta", "questions": [{"id": "q1", "label": "Plano"}]}],
        form={"q1": "jejum"},
    )

    runs = _get_note_runs(note)

    assert runs[0][0].startswith("Plano")
    # no trailing blank lines left by the per-group "\n"
    assert not runs[-1][0].endswith("\n")
    # same-styled neighbours are merged into a single run
    assert len(runs) == 1


def test_note_runs_of_a_template_without_questions_are_empty():
    """A template holding a single unnamed empty group renders nothing"""
    assert _get_note_runs(_note(template=[{"group": "", "questions": []}])) == []


def test_note_runs_tolerate_a_form_answered_with_a_select():
    """A select answer is read through its label, not printed as a dict"""
    note = _note(
        template=[{"group": "Triagem", "questions": [{"id": "q1", "label": "Risco"}]}],
        form={"q1": {"value": 2, "label": "Amarelo"}},
    )

    text = "".join([run for run, _ in _get_note_runs(note)])

    assert text == "Risco: Amarelo"


def test_note_runs_tolerate_a_missing_form():
    """A template without any answers still renders its labels"""
    note = _note(
        template=[{"group": "Triagem", "questions": [{"id": "q1", "label": "Risco"}]}]
    )

    text = "".join([run for run, _ in _get_note_runs(note)])

    assert text == "Risco: Sem resposta"


# --------------------------------------------------------------------------
# _get_institution_header_runs
# --------------------------------------------------------------------------


def test_institution_header_is_read_from_the_nav_header_memory():
    """The header printed above the note comes from the nav-header record"""
    with mock.patch.object(clinical_notes_pdf_service, "db", _mock_db("<b>HC</b>")):
        assert _get_institution_header_runs() == [("HC", True)]


def test_institution_header_is_empty_without_the_memory_record():
    """A schema that never configured a header prints none"""
    with mock.patch.object(clinical_notes_pdf_service, "db", _mock_db()):
        assert _get_institution_header_runs() == []


def test_institution_header_is_empty_when_the_record_has_no_value():
    """A blank record is treated like a missing one"""
    mock_db = _mock_db("x")
    mock_db.session.query.return_value.filter.return_value.first.return_value.value = (
        None
    )

    with mock.patch.object(clinical_notes_pdf_service, "db", mock_db):
        assert _get_institution_header_runs() == []


def test_institution_header_is_empty_when_the_value_has_no_header_key():
    """A record shaped for another purpose contributes no header"""
    mock_db = _mock_db("x")
    mock_db.session.query.return_value.filter.return_value.first.return_value.value = {
        "other": "y"
    }

    with mock.patch.object(clinical_notes_pdf_service, "db", mock_db):
        assert _get_institution_header_runs() == []


# --------------------------------------------------------------------------
# _add_logo
# --------------------------------------------------------------------------


def test_a_missing_logo_only_costs_the_document_its_logo():
    """Rendering must not fail because the logo file cannot be read"""
    with (
        mock.patch.object(clinical_notes_pdf_service, "db", _mock_db()),
        mock.patch.object(
            clinical_notes_pdf_service, "_LOGO_PATH", "/does/not/exist.png"
        ),
    ):
        pdf_bytes, sign_page, _ = build_note_pdf(_note(text="<p>ok</p>"))

    assert pdf_bytes.startswith(b"%PDF")
    assert sign_page == 1


# --------------------------------------------------------------------------
# build_note_pdf
# --------------------------------------------------------------------------


def test_build_note_pdf_returns_a_pdf_and_the_signature_anchor():
    """The bytes are a PDF and the signature lands on the first page"""
    with mock.patch.object(clinical_notes_pdf_service, "db", _mock_db()):
        pdf_bytes, sign_page, sign_pos_y = build_note_pdf(_note(text="<p>Nota</p>"))

    assert pdf_bytes.startswith(b"%PDF")
    assert sign_page == 1
    assert 0 < sign_pos_y < 1


def test_build_note_pdf_declares_the_modern_spec_version():
    """Some PDF validators refuse files declaring the ancient 1.3 spec"""
    with mock.patch.object(clinical_notes_pdf_service, "db", _mock_db()):
        pdf_bytes, _, _ = build_note_pdf(_note(text="<p>Nota</p>"))

    assert pdf_bytes.startswith(b"%PDF-1.7")


def test_build_note_pdf_renders_a_custom_form_note():
    """A primary-care note has no text column: the form is what gets printed"""
    note = _note(
        template=[
            {
                "group": "Anamnese",
                "questions": [{"id": "q1", "label": "Queixa"}],
            },
            {
                "group": "Conduta",
                "questions": [{"id": "q2", "label": "Plano"}],
            },
        ],
        form={"q1": "Dor", "q2": "Repouso"},
    )

    with mock.patch.object(clinical_notes_pdf_service, "db", _mock_db()):
        pdf_bytes, sign_page, sign_pos_y = build_note_pdf(note)

    assert pdf_bytes.startswith(b"%PDF")
    assert sign_page == 1
    assert 0 < sign_pos_y < 1


def test_build_note_pdf_of_an_empty_note_still_produces_a_document():
    """An empty body must not break the signature flow"""
    with mock.patch.object(clinical_notes_pdf_service, "db", _mock_db()):
        pdf_bytes, sign_page, sign_pos_y = build_note_pdf(_note())

    assert pdf_bytes.startswith(b"%PDF")
    assert sign_page == 1
    assert 0 < sign_pos_y < 1


def test_build_note_pdf_prints_the_institution_header():
    """The configured header adds content above the note body"""
    with mock.patch.object(clinical_notes_pdf_service, "db", _mock_db()):
        _, _, without_header = build_note_pdf(_note(text="<p>Nota</p>"))

    with mock.patch.object(
        clinical_notes_pdf_service, "db", _mock_db("<b>Hospital Teste</b><br>Centro")
    ):
        _, _, with_header = build_note_pdf(_note(text="<p>Nota</p>"))

    # the header, its separator line and the spacing push the body down
    assert with_header > without_header


def test_build_note_pdf_pushes_the_signature_to_the_last_page():
    """A long note breaks into pages: the field goes where the body ended"""
    long_text = "<p>" + ("Evolução detalhada do paciente. " * 400) + "</p>"

    with mock.patch.object(clinical_notes_pdf_service, "db", _mock_db()):
        _, sign_page, sign_pos_y = build_note_pdf(_note(text=long_text))

    assert sign_page > 1
    assert 0 < sign_pos_y < 1


def test_build_note_pdf_keeps_the_signature_above_the_bottom_margin():
    """The auto page break guarantees the field always fits on the page"""
    with mock.patch.object(clinical_notes_pdf_service, "db", _mock_db()):
        _, _, sign_pos_y = build_note_pdf(
            _note(text="<p>" + ("linha<br>" * 60) + "</p>")
        )

    # 297mm page with a 20mm bottom margin
    assert sign_pos_y < (297 - 20) / 297
