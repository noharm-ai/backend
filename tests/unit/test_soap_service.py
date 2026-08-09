"""Unit tests for services.soap_service pure content-building helpers.

These cover the pure, side-effect-free helpers that assemble the LLM prompt
input from a clinical note and clean up the model output. They do not touch
the database or the Bedrock client, so they run as fast unit tests.
"""

import json

from services import soap_service


class _Note:
    """Minimal stand-in for a ClinicalNotes row used by _get_note_content."""

    def __init__(self, date="", position="", prescriber="", form=None, template=None, text=None):
        self.date = date
        self.position = position
        self.prescriber = prescriber
        self.form = form
        self.template = template
        self.text = text


class TestStripCodeFences:
    """Tests for soap_service._strip_code_fences (LLM markdown fence removal)."""

    def test_plain_text_unchanged(self):
        """Text without fences is returned trimmed but otherwise intact."""
        assert soap_service._strip_code_fences("  <p>hello</p>  ") == "<p>hello</p>"

    def test_language_fence_is_removed(self):
        """A leading ```html fence line and trailing fence are stripped."""
        text = "```html\n<p>x</p>\n```"
        assert soap_service._strip_code_fences(text) == "<p>x</p>"

    def test_bare_fence_is_removed(self):
        """A bare ``` opening fence (no language) drops the first line."""
        text = "```\ncontent here\n```"
        assert soap_service._strip_code_fences(text) == "content here"

    def test_only_opening_fence_line_returns_empty(self):
        """A string that is only an opening fence with no newline becomes empty."""
        assert soap_service._strip_code_fences("```html") == ""

    def test_trailing_fence_only(self):
        """A trailing fence with no opening fence is still removed."""
        assert soap_service._strip_code_fences("some text```") == "some text"

    def test_multiline_body_preserved(self):
        """Inner newlines of the fenced body are preserved."""
        text = "```html\n<p>a</p>\n<p>b</p>\n```"
        assert soap_service._strip_code_fences(text) == "<p>a</p>\n<p>b</p>"


class TestGetFormContent:
    """Tests for soap_service._get_form_content (form answers -> Q/A text)."""

    def test_no_template_returns_pretty_json(self):
        """Without a template the raw form is dumped as indented JSON."""
        form = {"q1": "resposta"}
        result = soap_service._get_form_content(form=form, template=None)
        assert result == json.dumps(form, ensure_ascii=False, indent=2)

    def test_no_template_keeps_unicode(self):
        """The JSON fallback preserves accented characters (ensure_ascii=False)."""
        result = soap_service._get_form_content(form={"q": "avaliação"}, template=[])
        assert "avaliação" in result

    def test_renders_group_and_question_answer(self):
        """Answered questions are rendered under their group heading."""
        template = [
            {
                "group": "Anamnese",
                "questions": [{"id": "q1", "label": "Queixa principal"}],
            }
        ]
        form = {"q1": "dor de cabeça"}
        result = soap_service._get_form_content(form=form, template=template)
        assert "### Anamnese" in result
        assert "Pergunta: Queixa principal" in result
        assert "Resposta: dor de cabeça" in result

    def test_unanswered_questions_are_skipped(self):
        """Questions with empty/None/[] answers produce no output and no group."""
        template = [
            {
                "group": "Vazio",
                "questions": [
                    {"id": "a", "label": "A"},
                    {"id": "b", "label": "B"},
                ],
            }
        ]
        form = {"a": "", "b": None}
        result = soap_service._get_form_content(form=form, template=template)
        assert result == ""

    def test_list_answer_is_joined_with_commas(self):
        """A list-valued answer is rendered as a comma-separated string."""
        template = [
            {"group": "G", "questions": [{"id": "s", "label": "Sintomas"}]}
        ]
        form = {"s": ["febre", "tosse"]}
        result = soap_service._get_form_content(form=form, template=template)
        assert "Resposta: febre, tosse" in result

    def test_extra_form_keys_not_in_template_are_appended(self):
        """Answered keys absent from the template are appended by their raw key."""
        template = [
            {"group": "G", "questions": [{"id": "known", "label": "Conhecida"}]}
        ]
        form = {"known": "sim", "extra": "valor extra"}
        result = soap_service._get_form_content(form=form, template=template)
        assert "Resposta: sim" in result
        # extra key rendered using the key itself as the question label
        assert "Pergunta: extra" in result
        assert "Resposta: valor extra" in result

    def test_extra_empty_keys_are_ignored(self):
        """Extra form keys with empty answers are not appended."""
        template = [
            {"group": "G", "questions": [{"id": "known", "label": "Conhecida"}]}
        ]
        form = {"known": "sim", "empty": ""}
        result = soap_service._get_form_content(form=form, template=template)
        assert "Pergunta: empty" not in result


class TestGetNoteContent:
    """Tests for soap_service._get_note_content (build LLM user message)."""

    def test_includes_consultation_metadata(self):
        """The header always carries date, position and prescriber."""
        note = _Note(date="2024-01-01", position="Farmacêutico", prescriber="Ana")
        result = soap_service._get_note_content(note)
        assert "## Dados da consulta" in result
        assert "Data: 2024-01-01" in result
        assert "Cargo/Origem: Farmacêutico" in result
        assert "Responsável: Ana" in result

    def test_form_section_added_when_form_present(self):
        """A form section is appended when the note has form answers."""
        note = _Note(
            form={"q1": "resposta"},
            template=[{"group": "G", "questions": [{"id": "q1", "label": "Q"}]}],
        )
        result = soap_service._get_note_content(note)
        assert "## Formulário da consulta (perguntas e respostas)" in result
        assert "Resposta: resposta" in result

    def test_text_section_added_when_text_present(self):
        """The free-text evolution is appended under its own heading."""
        note = _Note(text="evolução livre")
        result = soap_service._get_note_content(note)
        assert "## Texto da evolução" in result
        assert "evolução livre" in result

    def test_text_is_truncated_to_max_chars(self):
        """Overly long note text is capped at SOAP_INPUT_MAX_CHARS characters."""
        long_text = "a" * (soap_service.SOAP_INPUT_MAX_CHARS + 500)
        note = _Note(text=long_text)
        result = soap_service._get_note_content(note)
        assert "a" * soap_service.SOAP_INPUT_MAX_CHARS in result
        assert "a" * (soap_service.SOAP_INPUT_MAX_CHARS + 1) not in result

    def test_optional_sections_absent_when_empty(self):
        """With no form and no text only the metadata header is produced."""
        note = _Note(date="2024-01-01")
        result = soap_service._get_note_content(note)
        assert "## Formulário da consulta (perguntas e respostas)" not in result
        assert "## Texto da evolução" not in result
