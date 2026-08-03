import pytest

from utils import stringutils


@pytest.mark.parametrize(
    "name, prepared_name",
    [
        ("ZINPASS 10mg 1cp/dia", "ZINPASS"),
        ("DOXAZOSINA 4mg 1cp/dia", "DOXAZOSINA"),
        ("ZINPASS 10mg 1cp/dia tardinha", "ZINPASS"),
        (
            "PANTOPRAZOL 40MG CPR - 1CPR - às 06:00 h - às 06:00 h",
            "PANTOPRAZOL  CPR 1CPR",
        ),
        ("PROPAFENONA 150MG - 1CPR - 09-21 h", "PROPAFENONA  1CPR"),
    ],
)
def test_prepare_drug_name(name, prepared_name):
    """Teste stringutils - prepare_drug_name"""

    assert stringutils.prepare_drug_name(name) == prepared_name


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, ""),
        ("", ""),
        (0, "0"),
        (5, "5"),
        ("abc", "abc"),
    ],
)
def test_str_none(value, expected):
    """Teste stringutils - strNone converts None to empty string, keeps others"""

    assert stringutils.strNone(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        (1234567.5, "1.234.567,50"),
        (0, "0,00"),
        (1000, "1.000,00"),
        (12.3, "12,30"),
    ],
)
def test_str_format_br(value, expected):
    """Teste stringutils - strFormatBR uses Brazilian number formatting"""

    assert stringutils.strFormatBR(value) == expected


def test_strip_control_chars():
    """Teste stringutils - strip_control_chars removes non-printable characters"""

    assert stringutils.strip_control_chars("a\x00b\tc\n") == "abc"
    assert stringutils.strip_control_chars("clean text") == "clean text"
    assert stringutils.strip_control_chars("") == ""


class TestTextToHtml:
    """Teste stringutils - text_to_html (used to render user text safely as HTML)"""

    def test_empty_returns_empty(self):
        """Empty / falsy input returns an empty string"""
        assert stringutils.text_to_html("") == ""
        assert stringutils.text_to_html(None) == ""

    def test_escapes_html_special_chars(self):
        """HTML special characters are escaped to prevent XSS injection"""
        assert (
            stringutils.text_to_html("Hello & <b>x</b>")
            == "Hello &amp; &lt;b&gt;x&lt;/b&gt;"
        )

    def test_escapes_script_tag(self):
        """A script tag is fully neutralized when escaped"""
        result = stringutils.text_to_html("<script>alert('xss')</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_newline_becomes_br(self):
        """Newlines become <br> tags when whitespace is preserved"""
        assert stringutils.text_to_html("a\nb") == "a<br>b"

    def test_multiple_spaces_preserved(self):
        """Runs of spaces are preserved with non-breaking spaces"""
        assert stringutils.text_to_html("a   b") == "a &nbsp;&nbsp;b"

    def test_tab_becomes_nbsp(self):
        """Tabs are converted to non-breaking spaces"""
        assert stringutils.text_to_html("a\tb") == "a&nbsp;&nbsp;&nbsp;&nbsp;b"

    def test_no_whitespace_preservation(self):
        """When preserve_whitespace is False newlines are still escaped but not converted"""
        result = stringutils.text_to_html("a\nb", preserve_whitespace=False)
        assert "<br>" not in result


class TestTruncate:
    """Teste stringutils - truncate (safe string truncation)"""

    def test_none_returns_empty(self):
        """None / empty input returns an empty string"""
        assert stringutils.truncate(None, 8) == ""
        assert stringutils.truncate("", 8) == ""

    def test_non_positive_max_length_returns_empty(self):
        """A non-positive max_length returns an empty string"""
        assert stringutils.truncate("abc", 0) == ""
        assert stringutils.truncate("abc", -5) == ""

    def test_short_text_unchanged(self):
        """Text shorter than max_length is returned untouched"""
        assert stringutils.truncate("Hello World", 20) == "Hello World"

    def test_truncates_with_ellipsis(self):
        """Longer text is truncated and ellipsis appended"""
        assert stringutils.truncate("Hello World", 8) == "Hello..."

    def test_custom_ellipsis(self):
        """A custom ellipsis is honored"""
        assert stringutils.truncate("Hello World", 8, ellipsis="…") == "Hello…"

    def test_result_never_exceeds_max_length(self):
        """The truncated result never exceeds max_length"""
        result = stringutils.truncate("Hello World", 8)
        assert len(result) <= 8

    def test_word_boundary_disabled(self):
        """Result is still within bounds when word boundary handling is off"""
        result = stringutils.truncate("Hello World", 8, word_boundary=False)
        assert len(result) <= 8


class TestIsValidFilename:
    """Teste stringutils - is_valid_filename (path-traversal protection)"""

    @pytest.mark.parametrize(
        "path",
        [
            "file.txt",
            "folder/file.txt",
            "a/b/c/file_1.pdf",
            "report-2024.csv",
        ],
    )
    def test_valid_paths(self, path):
        """Well-formed relative paths are accepted"""
        assert stringutils.is_valid_filename(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "",
            "../etc/passwd",
            "folder/../secret",
            "a\\b",
            "%2e%2e/x",
            "%2f",
            "file with space.txt",
            "file$name.txt",
        ],
    )
    def test_invalid_paths(self, path):
        """Traversal, encoded traversal and illegal characters are rejected"""
        assert stringutils.is_valid_filename(path) is False

    def test_null_byte_rejected(self):
        """Null byte injection is rejected"""
        assert stringutils.is_valid_filename("a\x00b.txt") is False

    def test_valid_extension_accepted(self):
        """A path with an allowed extension passes the extension check"""
        assert stringutils.is_valid_filename("report.pdf", {".pdf", ".csv"}) is True

    def test_invalid_extension_rejected(self):
        """A path whose extension is not allowed is rejected"""
        assert stringutils.is_valid_filename("report.txt", {".pdf", ".csv"}) is False


class TestRemoveAccents:
    """Teste stringutils - remove_accents (diacritic stripping)"""

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("ção", b"cao"),
            ("Olá Mundo", b"Ola Mundo"),
            ("ÁÉÍÓÚ", b"AEIOU"),
            ("ascii", b"ascii"),
        ],
    )
    def test_strips_accents_returning_bytes(self, value, expected):
        """Accents are removed; the result is an ASCII byte string."""
        assert stringutils.remove_accents(value) == expected


class TestSlugify:
    """Teste stringutils - slugify (used as a grouping key)"""

    def test_lowercases_and_replaces_non_word_runs(self):
        """Non-word runs collapse to dashes and the text is lowercased.

        Note: remove_accents returns bytes, so slugify currently includes the
        byte-string repr in its output. These assertions document the current
        behavior rather than an idealized slug.
        """
        assert stringutils.slugify("Hello World") == "b-hello-world-"

    def test_strips_accents_before_slugifying(self):
        """Accented characters are stripped before the slug is built."""
        assert stringutils.slugify("Ação Média") == "b-acao-media-"
