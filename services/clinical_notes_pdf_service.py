"""Service: renders a clinical note (free text or custom form) as a PDF.

The document is built with FPDF core fonts, so the text is coerced to latin-1
and the emphasis of the original note is kept by writing it run by run.
"""

import os

from fpdf import FPDF

from models.appendix import Memory
from models.main import db
from models.notes import ClinicalNotes
from utils import logger
from utils.htmlutils import html_to_runs, normalize_runs

_A4_HEIGHT_MM = 297

# logo printed above the institution header (width as a fraction of the page)
_LOGO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
    "logo512.png",
)
_LOGO_WIDTH_RATIO = 0.05

# style markers understood by FPDF's markdown mode
_MARKDOWN_MARKERS = ("**", "__", "~~", "--")


def _to_latin1(text: str) -> str:
    """Coerces text to latin-1 (PDF core fonts), replacing unsupported chars."""
    return (text or "").encode("latin-1", "replace").decode("latin-1")


def _runs_to_markdown(runs: list[tuple[str, bool]]) -> str:
    """Renders runs in the markdown subset FPDF understands (bold only).

    Used where the text must also be aligned (FPDF only honors align in
    multi_cell, which takes markdown instead of per-run font changes). Marker
    sequences already present in the text are escaped so they get printed
    instead of toggling a style.
    """
    parts = []

    for text, bold in runs:
        for marker in _MARKDOWN_MARKERS:
            text = text.replace(marker, f"\\{marker}")

        parts.append(f"**{text}**" if bold else text)

    return "".join(parts)


def _format_form_value(value) -> str:
    """Formats a custom form answer the same way the frontend renders it."""
    if value is None or value == "":
        return "Sem resposta"

    if isinstance(value, list):
        return ", ".join([str(item) for item in value])

    if isinstance(value, dict):
        return str(value.get("label", ""))

    return str(value)


def _get_note_runs(note: ClinicalNotes) -> list[tuple[str, bool]]:
    """Extracts the printable body of a clinical note (free text or custom form)
    as (text, bold) runs."""
    if note.text:
        return html_to_runs(note.text)

    if note.template:
        parts: list[tuple[str, bool]] = []
        form = note.form or {}

        # a single group carries no grouping information, so its name is omitted
        print_group_names = len(note.template) > 1

        for group in note.template:
            group_name = str(group.get("group", ""))
            if group_name and print_group_names:
                parts.append((f"{group_name}\n", False))

            for question in group.get("questions", []):
                label = str(question.get("label", "") or "")
                value = _format_form_value(form.get(str(question.get("id"))))

                # unlabeled questions (free letters, for instance) are printed
                # without the "label: " prefix
                if label:
                    parts.append((f"{label}: ", False))

                parts.extend(html_to_runs(value))
                parts.append(("\n", False))

            parts.append(("\n", False))

        return normalize_runs(parts)

    return []


def _get_institution_header_runs() -> list[tuple[str, bool]]:
    """Gets the institution header configured in the nav-header memory record."""
    memory = db.session.query(Memory).filter(Memory.kind == "nav-header").first()

    if memory and memory.value:
        return html_to_runs(memory.value.get("header", ""))

    return []


def _add_logo(pdf: FPDF) -> None:
    """Draws the logo centered on the line above the institution header.

    Best effort: a missing or unreadable file only costs the document its logo.
    """
    try:
        width = pdf.w * _LOGO_WIDTH_RATIO
        image = pdf.image(_LOGO_PATH, x=(pdf.w - width) / 2, y=pdf.get_y(), w=width)

        # pdf.image() does not move the cursor
        pdf.set_y(pdf.get_y() + image.rendered_height)
        pdf.ln(3)
    except Exception as error:  # pylint: disable=broad-except
        logger.backend_logger.warning(
            "ODOO Sign: could not add the logo from %s (%s)", _LOGO_PATH, error
        )


def build_note_pdf(note: ClinicalNotes) -> tuple[bytes, int, float]:
    """Builds the clinical note PDF.

    Returns the PDF bytes, the page where the signature field must be placed
    and its vertical position as a fraction (0-1) of the page height.
    """
    pdf = FPDF(format="A4")
    # some PDF validators refuse files declaring the ancient 1.3 spec
    pdf.pdf_version = "1.7"
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    _add_logo(pdf)

    institution_header = _get_institution_header_runs()
    if institution_header:
        pdf.set_font("helvetica", size=9)
        pdf.multi_cell(
            w=0,
            h=4.5,
            text=_to_latin1(_runs_to_markdown(institution_header)),
            align="C",
            markdown=True,
        )
        pdf.ln(2)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(6)

    # written run by run (instead of a single multi_cell) so the emphasis used
    # in the note is preserved
    body_line_height = 5
    for text, bold in _get_note_runs(note):
        pdf.set_font("helvetica", style="B" if bold else "", size=10)
        pdf.write(h=body_line_height, text=_to_latin1(text))

    # write() leaves the cursor on the last line: close it like multi_cell does
    pdf.ln(body_line_height)

    # the note text carries its own signature block, so nothing is drawn here:
    # the signature field is anchored right where the body ended. The auto page
    # break keeps the body above the bottom margin, so the field always fits.
    sign_page = pdf.page_no()
    sign_pos_y = pdf.get_y() / _A4_HEIGHT_MM

    return bytes(pdf.output()), sign_page, sign_pos_y
