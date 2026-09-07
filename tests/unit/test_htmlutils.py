"""Unit tests for utils.htmlutils — HTML fragments to styled text runs.

The rich text editors used for clinical notes and for the institution header
store HTML. ``html_to_runs`` turns that HTML into a list of ``(text, bold)``
runs so consumers (the clinical note PDF, for instance) can reproduce the
emphasis the user typed instead of printing raw markup.

Everything here is pure string handling, so these are plain unit tests: no
Flask context, no database.
"""

import pytest

from utils.htmlutils import html_to_runs, normalize_runs


def _text(runs):
    """Concatenate the text of every run, ignoring the emphasis."""
    return "".join([text for text, _ in runs])


@pytest.mark.parametrize("empty", ["", None])
def test_empty_html_produces_no_runs(empty):
    """An empty (or missing) fragment short-circuits to an empty run list."""
    assert html_to_runs(empty) == []


def test_plain_text_without_markup_is_a_single_unstyled_run():
    """Text with no tags at all comes back as one non-bold run."""
    assert html_to_runs("plain text no tags") == [("plain text no tags", False)]


def test_paragraph_text_is_unwrapped():
    """The tags are dropped and only their text content is kept."""
    assert html_to_runs("<p>Hello</p>") == [("Hello", False)]


def test_html_entities_are_decoded():
    """Character references are resolved (the parser runs with convert_charrefs)."""
    assert html_to_runs("<p>a &amp; b</p>") == [("a & b", False)]


# ---------------------------------------------------------------------------
# emphasis
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tag", ["b", "strong"])
def test_bold_tags_mark_their_text(tag):
    """<b> and <strong> split the text into a bold run."""
    runs = html_to_runs(f"<p>Hello <{tag}>world</{tag}>!</p>")

    assert runs == [("Hello ", False), ("world", True), ("!", False)]


@pytest.mark.parametrize("tag", ["h1", "h2", "h3", "h4", "h5", "h6"])
def test_headings_are_bold_and_break_the_line(tag):
    """Headings are emphasized and, being block tags, end their line."""
    runs = html_to_runs(f"<{tag}>Title</{tag}><p>Body</p>")

    assert runs == [("Title", True), ("\nBody", False)]


def test_table_header_cell_is_bold_and_data_cell_is_not():
    """<th> carries emphasis; <td> does not."""
    runs = html_to_runs("<table><tr><th>Exame</th><td>Resultado</td></tr></table>")

    assert runs == [("Exame", True), ("Resultado", False)]


@pytest.mark.parametrize(
    "style",
    [
        "font-weight: bold",
        "font-weight:bolder",
        "font-weight: 600",
        "font-weight:700",
        "font-weight : 900",
        "FONT-WEIGHT: BOLD",
    ],
)
def test_inline_font_weight_styles_are_bold(style):
    """A bold inline font-weight makes the element's text a bold run."""
    assert html_to_runs(f'<span style="{style}">x</span>') == [("x", True)]


@pytest.mark.parametrize(
    "style", ["font-weight: normal", "font-weight:400", "font-weight:500", "color:red"]
)
def test_other_inline_styles_are_not_bold(style):
    """Anything below 600 (or unrelated) leaves the text unstyled."""
    assert html_to_runs(f'<span style="{style}">x</span>') == [("x", False)]


def test_emphasis_is_inherited_by_nested_elements():
    """Text nested inside a bold element stays bold."""
    runs = html_to_runs("<b>outer <span>inner</span></b>")

    assert runs == [("outer inner", True)]


def test_adjacent_runs_with_the_same_emphasis_are_merged():
    """Consecutive same-styled parts are collapsed into a single run."""
    runs = html_to_runs("<p><b>A</b><strong>B</strong>C</p>")

    assert runs == [("AB", True), ("C", False)]


def test_closing_a_bold_element_stops_the_emphasis():
    """Emphasis does not leak past the element that opened it."""
    runs = html_to_runs("<p><b>bold</b>plain<b>bold again</b></p>")

    assert runs == [("bold", True), ("plain", False), ("bold again", True)]


# ---------------------------------------------------------------------------
# line breaks
# ---------------------------------------------------------------------------


def test_br_becomes_a_line_break():
    """<br> is a newline inside the current run."""
    assert html_to_runs("<p>Line one<br>Line two</p>") == [
        ("Line one\nLine two", False)
    ]


def test_br_inherits_the_current_emphasis():
    """A break inside a bold element belongs to the bold run."""
    runs = html_to_runs("<b>one<br>two</b>")

    assert runs == [("one\ntwo", True)]


@pytest.mark.parametrize(
    "html",
    [
        "<p>A</p><p>B</p>",
        "<div>A</div><div>B</div>",
        "<ul><li>A</li><li>B</li></ul>",
        "<blockquote>A</blockquote><section>B</section>",
    ],
)
def test_block_tags_break_the_line(html):
    """Closing a block element starts a new line."""
    assert html_to_runs(html) == [("A\nB", False)]


def test_void_tags_do_not_break_the_line():
    """Self-closing tags other than <br> neither break nor open a scope."""
    assert html_to_runs("<p>Antes<img src='a.png'><hr>Depois</p>") == [
        ("AntesDepois", False)
    ]


def test_at_most_one_blank_line_is_kept():
    """Runs of empty paragraphs collapse to a single blank line."""
    html = "<p>A</p><p></p><p></p><p></p><p>B</p>"

    assert html_to_runs(html) == [("A\n\nB", False)]


def test_spaces_before_a_line_break_are_dropped():
    """Trailing whitespace on a line is trimmed when the line ends."""
    assert html_to_runs("<p>trailing   <br>next</p>") == [("trailing\nnext", False)]


def test_surrounding_whitespace_is_trimmed():
    """Leading and trailing whitespace of the whole fragment is removed."""
    assert html_to_runs("  <p>  spaced   </p>  ") == [("spaced", False)]


def test_a_fragment_with_only_markup_and_whitespace_produces_no_runs():
    """Empty paragraphs and breaks alone leave nothing to print."""
    assert html_to_runs("<p></p><p>  </p><br>") == []


# ---------------------------------------------------------------------------
# annotation close buttons
# ---------------------------------------------------------------------------


def test_annotation_close_button_text_is_skipped():
    """The "X" of an annotation close button must not leak into the document."""
    runs = html_to_runs('<p>note <a class="close-btn" href="#">X</a> tail</p>')

    assert _text(runs) == "note  tail"


def test_close_button_detection_accepts_extra_classes():
    """The close button is recognized when it carries other classes too."""
    runs = html_to_runs('<p>note <a class="tag close-btn">X</a> tail</p>')

    assert _text(runs) == "note  tail"


def test_regular_anchor_text_is_kept():
    """A plain link keeps its text — only close buttons are dropped."""
    runs = html_to_runs('<p>keep <a href="#">link text</a> here</p>')

    assert runs == [("keep link text here", False)]


def test_text_after_a_close_button_is_no_longer_skipped():
    """Skipping ends with the anchor, so following content is printed."""
    runs = html_to_runs('<a class="close-btn">X</a>after')

    assert runs == [("after", False)]


# ---------------------------------------------------------------------------
# malformed markup
# ---------------------------------------------------------------------------


def test_unclosed_bold_applies_until_the_end():
    """An element left open keeps styling the rest of the fragment."""
    runs = html_to_runs("<b>bold to the end")

    assert runs == [("bold to the end", True)]


def test_closing_an_inner_element_does_not_reopen_the_outer_one():
    """Closing an element drops whatever was left open inside it."""
    runs = html_to_runs("<p><b>bold <i>italic</b> plain</p>")

    assert runs == [("bold italic", True), (" plain", False)]


def test_closing_tag_without_a_matching_open_is_tolerated():
    """A stray closing block tag still breaks the line and styling survives."""
    runs = html_to_runs("<b>unbalanced</p> after")

    assert runs == [("unbalanced", True), ("\n", False), (" after", True)]


def test_unknown_tags_are_transparent():
    """A tag that is neither block nor bold only contributes its text."""
    assert html_to_runs("<custom>text</custom>") == [("text", False)]


# ---------------------------------------------------------------------------
# normalize_runs (used directly to assemble custom form answers)
# ---------------------------------------------------------------------------


def test_normalize_runs_on_an_empty_list():
    """Nothing in, nothing out."""
    assert normalize_runs([]) == []


def test_normalize_runs_trims_and_collapses_blank_lines():
    """Whitespace around the text is trimmed and blank lines are collapsed."""
    parts = [("  a  ", False), ("\n\n\n\n", False), ("b\n\n", False)]

    assert normalize_runs(parts) == [("a\n\nb", False)]


def test_normalize_runs_merges_parts_sharing_the_same_emphasis():
    """Same-styled neighbours become one run; a style change starts a new one."""
    parts = [("a", True), ("b", True), ("c", False), ("d", True)]

    assert normalize_runs(parts) == [("ab", True), ("c", False), ("d", True)]


def test_normalize_runs_keeps_the_emphasis_of_each_character():
    """A label/value pair keeps the label unstyled and the answer bold."""
    parts = [("Peso: ", False), ("80", True), ("\n", False)]

    assert normalize_runs(parts) == [("Peso: ", False), ("80", True)]


def test_normalize_runs_drops_whitespace_only_input():
    """Input made of whitespace only normalizes to an empty list."""
    assert normalize_runs([(" \n ", False), ("\t\n", True)]) == []
