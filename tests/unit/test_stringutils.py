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
        (5, "5"),
        ("text", "text"),
        (0, "0"),
        (False, "False"),
    ],
)
def test_strNone(value, expected):
    """Teste stringutils - strNone converts None to empty string, otherwise str()"""

    assert stringutils.strNone(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        (1234.5, "1.234,50"),
        (1234567.89, "1.234.567,89"),
        (5, "5,00"),
        (0, "0,00"),
        (999, "999,00"),
    ],
)
def test_strFormatBR(value, expected):
    """Teste stringutils - strFormatBR formats numbers in Brazilian notation"""

    assert stringutils.strFormatBR(value) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("abc", "abc"),
        ("a\x00b", "ab"),
        ("a\tb\nc", "abc"),
        ("hello world", "hello world"),
        ("", ""),
    ],
)
def test_strip_control_chars(text, expected):
    """Teste stringutils - strip_control_chars removes non-printable characters"""

    assert stringutils.strip_control_chars(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        # HTML special characters are escaped to prevent XSS
        ("Hello & goodbye", "Hello &amp; goodbye"),
        (
            "<script>alert('xss')</script>",
            "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;",
        ),
        # Newlines become <br> tags when whitespace is preserved
        ("Line 1\nLine 2", "Line 1<br>Line 2"),
        # Empty input is returned unchanged
        ("", ""),
    ],
)
def test_text_to_html(text, expected):
    """Teste stringutils - text_to_html escapes HTML and preserves line breaks"""

    assert stringutils.text_to_html(text) == expected


def test_text_to_html_without_whitespace_preservation():
    """Teste stringutils - text_to_html without whitespace preservation keeps escaping only"""

    result = stringutils.text_to_html("Line 1\nLine 2", preserve_whitespace=False)

    assert result == "Line 1\nLine 2"


def test_text_to_html_collapses_multiple_spaces():
    """Teste stringutils - text_to_html converts extra spaces to non-breaking spaces"""

    assert stringutils.text_to_html("a   b") == "a &nbsp;&nbsp;b"


@pytest.mark.parametrize(
    "text, max_length, expected",
    [
        # Truncates on word boundary and appends ellipsis
        ("Hello World", 8, "Hello..."),
        # Returns text unchanged when it already fits
        ("Hello World", 20, "Hello World"),
        # Falsy input returns empty string
        (None, 8, ""),
        ("", 8, ""),
        # Non-positive max_length returns empty string
        ("abc", 0, ""),
        ("abc", -5, ""),
    ],
)
def test_truncate(text, max_length, expected):
    """Teste stringutils - truncate shortens text respecting boundaries and edge cases"""

    assert stringutils.truncate(text, max_length) == expected


def test_truncate_custom_ellipsis():
    """Teste stringutils - truncate honors a custom ellipsis string"""

    assert stringutils.truncate("Hello World", 8, ellipsis="…") == "Hello…"


@pytest.mark.parametrize(
    "resource_path, valid_extensions, expected",
    [
        # Valid, simple filenames and paths
        ("report.pdf", None, True),
        ("folder/report.pdf", None, True),
        ("UPPER_case-1.2.PDF", None, True),
        # Empty path is rejected
        ("", None, False),
        # Path traversal attempts are rejected
        ("../etc/passwd", None, False),
        ("folder/../secret", None, False),
        ("a\\b", None, False),
        # URL-encoded traversal / separators are rejected
        ("file%2e%2e", None, False),
        ("file%2f", None, False),
        # Null byte injection is rejected
        ("file\x00.pdf", None, False),
        # Disallowed characters are rejected
        ("file!.pdf", None, False),
        # Extension whitelist is enforced
        ("report.pdf", {".pdf"}, True),
        ("report.txt", {".pdf"}, False),
    ],
)
def test_is_valid_filename(resource_path, valid_extensions, expected):
    """Teste stringutils - is_valid_filename blocks path traversal and enforces extensions"""

    assert stringutils.is_valid_filename(resource_path, valid_extensions) == expected
