"""Utils: string related functions"""

import html
import re
import unicodedata
from typing import Union
from urllib.parse import unquote


def strNone(s):
    return "" if s is None else str(s)


def strFormatBR(s):
    return f"{s:_.2f}".replace(".", ",").replace("_", ".")


def remove_accents(text):
    nfkd_form = unicodedata.normalize("NFKD", text)
    only_ascii = nfkd_form.encode("ASCII", "ignore")
    return only_ascii


def slugify(text):
    text = remove_accents(text).lower()
    return re.sub(r"[\W_]+", "-", str(text))


def prepare_drug_name(name):
    bad_words = [
        n.upper()
        for n in [
            "manhã",
            "manha",
            "noite",
            "pela",
            "café",
            "cafe",
            "dia",
            "conforme",
            "HGT",
            "antes",
            "1cp",
            "2cp",
            "almoço",
            "almoco",
            "das",
            "refeições",
            "refeicoes",
            "jejum",
            "semana",
            "horas",
            "segunda",
            "terça",
            "terca",
            "quarta",
            "quinta",
            "sexta",
            "sábado",
            "sabado",
            "domingo",
            "ao",
            "as",
            "às",
            "tardinha",
        ]
    ]

    # Compile regex patterns for cleaning
    time_pattern = re.compile(r"\d{1,2}[\-\/:]\d{1,2}")  # Matches patterns like 12-12
    dosage_pattern = re.compile(
        r"\d{1,2}[a-zA-Z]{1,3}\/?(dia|hora|semana)", flags=re.IGNORECASE
    )  # Matches patterns like 3x/dia

    words = name.split()
    filtered_words = [
        word.upper()
        for word in words
        if word.upper() not in bad_words and len(word) >= 2
    ]

    if filtered_words:
        cleaned_name = " ".join(filtered_words)
        cleaned_name = time_pattern.sub(" ", cleaned_name)  # Remove time patterns
        cleaned_name = dosage_pattern.sub(" ", cleaned_name)  # Remove dosage patterns
        return cleaned_name.strip()

    return " ".join(words).upper()


def is_valid_filename(
    resource_path: str,
    valid_extensions: Union[set[str], None] = None,
):
    if not resource_path:
        return False

    # Decode URL encoding to prevent encoded path traversal attacks
    # Decode multiple times to catch double-encoding
    decoded_path = resource_path
    max_iterations = 3
    for _ in range(max_iterations):
        new_decoded = unquote(decoded_path)
        if new_decoded == decoded_path:
            break
        decoded_path = new_decoded

    # Check for path traversal attempts in both original and decoded
    for path_to_check in [resource_path, decoded_path]:
        if ".." in path_to_check or "\\" in path_to_check:
            return False

    # Prevent null byte injection (check both encoded and decoded)
    if "\x00" in resource_path or "\x00" in decoded_path:
        return False

    # Check for URL-encoded path traversal patterns
    dangerous_patterns = [
        r"%2e%2e",  # ..
        r"%2f",  # /
        r"%5c",  # \
        r"%00",  # null byte
    ]
    lower_path = resource_path.lower()
    for pattern in dangerous_patterns:
        if pattern in lower_path:
            return False

    # Validate full path with directories
    # Allow alphanumeric, dash, underscore, dot, and forward slash for paths
    if not re.match(r"^[\w\-\./]+$", resource_path):
        return False

    # Check each path component
    parts = resource_path.split("/")
    for part in parts:
        if part and not re.match(r"^[\w\-\.]+$", part):
            return False

    # Ensure resource_path has valid extension
    if valid_extensions:
        if not any(resource_path.endswith(ext) for ext in valid_extensions):
            return False

    return True


def text_to_html(text: str, preserve_whitespace: bool = True) -> str:
    """
    Convert plain text to HTML with proper escaping and formatting.

    Args:
        text: Plain text string to convert
        preserve_whitespace: If True, preserves line breaks and multiple spaces

    Returns:
        HTML-formatted string with escaped special characters

    Examples:
        >>> text_to_html("Hello & goodbye")
        'Hello &amp; goodbye'

        >>> text_to_html("Line 1\\nLine 2")
        'Line 1<br>Line 2'

        >>> text_to_html("<script>alert('xss')</script>")
        '&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;'
    """
    if not text:
        return ""

    # Escape HTML special characters
    escaped_text = html.escape(text, quote=True)

    if preserve_whitespace:
        # Replace newlines with <br> tags
        escaped_text = escaped_text.replace("\n", "<br>")
        escaped_text = escaped_text.replace("\r\n", "<br>")
        escaped_text = escaped_text.replace("\r", "<br>")

        # Replace multiple spaces with non-breaking spaces
        # Keep first space as regular space, convert rest to &nbsp;
        escaped_text = re.sub(
            r" {2,}", lambda m: " " + "&nbsp;" * (len(m.group()) - 1), escaped_text
        )

        # Replace tabs with spaces
        escaped_text = escaped_text.replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;")

    return escaped_text
