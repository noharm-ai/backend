"""Utilities to convert HTML fragments into styled text runs.

A run is a (text, bold) pair: the emphasis used by the rich text editors
(<b>, <strong>, inline font-weight and headings) is preserved so consumers
(PDF generation, for instance) can reproduce what the user typed.
"""

import re
from html.parser import HTMLParser
from itertools import groupby


class _HtmlTextExtractor(HTMLParser):
    """Converts an HTML fragment into text runs.

    A run is a (text, bold) pair: the emphasis used by the note editor
    (<b>, <strong>, inline font-weight and headings) is kept so the PDF looks
    like what the user typed.
    """

    _BLOCK_TAGS = {
        "p",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "tr",
        "table",
        "ul",
        "ol",
        "section",
        "article",
        "blockquote",
    }

    _BOLD_TAGS = {"b", "strong", "th", "h1", "h2", "h3", "h4", "h5", "h6"}

    _VOID_TAGS = {"br", "hr", "img", "input", "meta", "link", "col", "source"}

    _BOLD_STYLE_REGEX = re.compile(
        r"font-weight\s*:\s*(bold|bolder|[6-9]00)", re.IGNORECASE
    )

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts: list[tuple[str, bool]] = []
        self._skip_anchor = False
        # open elements as (tag, bold), used to know the style of each text run
        self._open_tags: list[tuple[str, bool]] = []

    def _is_bold(self) -> bool:
        """Tells whether the current position is inside a bold element."""
        return any(bold for _, bold in self._open_tags)

    def handle_starttag(self, tag, attrs):
        """Handles opening tags: line breaks, emphasis and close buttons."""
        attrs_dict = dict(attrs)

        if tag == "br":
            self._parts.append(("\n", self._is_bold()))
        elif tag == "a":
            # annotation close buttons ("X") must not leak into the document
            if "close-btn" in (attrs_dict.get("class") or ""):
                self._skip_anchor = True

        if tag not in self._VOID_TAGS:
            bold = tag in self._BOLD_TAGS or bool(
                self._BOLD_STYLE_REGEX.search(attrs_dict.get("style") or "")
            )
            self._open_tags.append((tag, bold))

    def handle_endtag(self, tag):
        """Handles closing tags: block tags become line breaks."""
        for index in range(len(self._open_tags) - 1, -1, -1):
            if self._open_tags[index][0] == tag:
                # closes the innermost matching element (and anything left open
                # inside it, so unbalanced markup does not leak its style)
                self._open_tags = self._open_tags[:index]
                break

        if tag == "a":
            self._skip_anchor = False
        elif tag in self._BLOCK_TAGS:
            self._parts.append(("\n", False))

    def handle_data(self, data):
        """Collects text content outside skipped elements."""
        if not self._skip_anchor:
            self._parts.append((data, self._is_bold()))

    def get_runs(self) -> list[tuple[str, bool]]:
        """Returns the extracted (text, bold) runs with collapsed blank lines."""
        return normalize_runs(self._parts)


def normalize_runs(parts: list[tuple[str, bool]]) -> list[tuple[str, bool]]:
    """Trims the text, collapses blank lines and merges same-styled parts."""
    chars: list[tuple[str, bool]] = []

    for text, bold in parts:
        for char in text:
            if char == "\n":
                # drop trailing spaces and never keep more than one blank line
                while chars and chars[-1][0] in " \t":
                    chars.pop()
                if len(chars) > 1 and chars[-1][0] == "\n" == chars[-2][0]:
                    continue

            chars.append((char, bold))

    start, end = 0, len(chars)
    while start < end and chars[start][0].isspace():
        start += 1
    while end > start and chars[end - 1][0].isspace():
        end -= 1

    return [
        ("".join([char for char, _ in group]), bold)
        for bold, group in groupby(chars[start:end], key=lambda item: item[1])
    ]


def html_to_runs(html: str) -> list[tuple[str, bool]]:
    """Converts an HTML fragment into (text, bold) runs."""
    if not html:
        return []

    parser = _HtmlTextExtractor()
    parser.feed(html)
    parser.close()

    return parser.get_runs()
