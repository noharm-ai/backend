"""Service: digital signature of clinical notes through the ODOO Sign module.

The flow mirrors the standard ODOO Sign integration:
1. ir.attachment        -> uploads the generated PDF (base64)
2. sign.template        -> points to the attachment
3. sign.item            -> places the signature field (fractions of the page, 0-1)
4. sign.send.request    -> defines the signer and triggers the e-mail
5. sign.request.item    -> access_token used to build the direct signing link

Two Sign model layouts are supported (detected at runtime via fields_get):
- up to ODOO 18: the PDF lives on sign.template.attachment_id and sign.item
  points to template_id;
- ODOO 19+: sign.template holds sign.document records (document_ids); the
  upload goes through sign.template.create_from_attachment_data (list of
  {"name", "raw"} dicts), documents point to their attachment and
  sign.item points to document_id.

ODOO 19 also removed ir.attachment.datas: the file content is written through
"raw" (still a base64 string over XML-RPC). Writing an unknown field on create
is silently ignored, so using "datas" there yields a 0-byte attachment and the
misleading "we're not able to process one of the uploaded pdf" error.
"""

import base64
import os
import re
import xmlrpc.client
from datetime import datetime
from html.parser import HTMLParser
from itertools import groupby

from fpdf import FPDF
from sqlalchemy.orm import undefer

from config import Config
from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import Memory
from models.main import User, db
from models.notes import ClinicalNotes
from models.requests.clinical_notes_request import ClinicalNoteSignRequest
from services import odoo_client
from utils import logger, status

_EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

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

# signature field footprint (fractions of the page, as expected by sign.item).
# posX left-aligns the field with the 10mm left margin FPDF gives the text.
_SIGN_ITEM_POS_X = 10 / 210
_SIGN_ITEM_WIDTH = 0.3
_SIGN_ITEM_HEIGHT = 0.05


class _HtmlTextExtractor(HTMLParser):
    """Converts the clinical note HTML into text runs suitable for the PDF.

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
        return _normalize_runs(self._parts)

def _normalize_runs(parts: list[tuple[str, bool]]) -> list[tuple[str, bool]]:
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


def _html_to_runs(html: str) -> list[tuple[str, bool]]:
    """Converts an HTML fragment into (text, bold) runs."""
    if not html:
        return []

    parser = _HtmlTextExtractor()
    parser.feed(html)
    parser.close()

    return parser.get_runs()


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
        return _html_to_runs(note.text)

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

                parts.extend(_html_to_runs(value))
                parts.append(("\n", False))

            parts.append(("\n", False))

        return _normalize_runs(parts)

    return []


def _get_institution_header_runs() -> list[tuple[str, bool]]:
    """Gets the institution header configured in the nav-header memory record."""
    memory = db.session.query(Memory).filter(Memory.kind == "nav-header").first()

    if memory and memory.value:
        return _html_to_runs(memory.value.get("header", ""))

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


def _build_note_pdf(note: ClinicalNotes) -> tuple[bytes, int, float]:
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


def _odoo_execute(client, **kwargs):
    """Executes an ODOO call and converts a timeout (None) into a 504 error.

    Business errors raised by ODOO (xmlrpc fault code 2, e.g. UserError)
    surface as a 400 with the original message instead of a raw fault.
    """
    try:
        result = client(**kwargs)
    except xmlrpc.client.Fault as fault:
        logger.backend_logger.warning(
            "ODOO Sign: %s.%s failed (fault %s): %s",
            kwargs.get("model"),
            kwargs.get("action"),
            fault.faultCode,
            fault.faultString,
        )

        if fault.faultCode == 2:
            raise ValidationError(
                f"Serviço de assinatura digital: {fault.faultString}",
                "errors.invalidParam",
                status.HTTP_400_BAD_REQUEST,
            ) from fault
        raise

    if result is None:
        raise ValidationError(
            "Não foi possível conectar ao serviço de assinatura digital.",
            "errors.connectionTimeout",
            status.HTTP_504_GATEWAY_TIMEOUT,
        )

    return result


def _get_model_fields(client, model: str) -> set:
    """Lists the field names of an ODOO model (used for version introspection)."""
    fields = _odoo_execute(
        client,
        model=model,
        action="fields_get",
        payload=[],
        options={"attributes": ["type"]},
    )

    return set(fields.keys())


def _get_attachment_data_field(client) -> str:
    """Returns the ir.attachment field that carries the file content.

    ODOO <= 18 exposes "datas"; ODOO 19 dropped it and keeps only "raw".
    Both take a base64 string over XML-RPC.
    """
    if "datas" in _get_model_fields(client, "ir.attachment"):
        return "datas"

    return "raw"


def _try_template_upload_method(client, method: str, payload: list):
    """Calls one of the sign.template upload helpers (they vary per ODOO
    version) and returns the created template id, or None when the method is
    unavailable or rejected the file (some versions return 0 instead of
    raising)."""
    try:
        result = client(
            model="sign.template",
            action=method,
            payload=payload,
            options={},
        )
    except xmlrpc.client.Fault as fault:
        logger.backend_logger.warning(
            "ODOO Sign: sign.template.%s unavailable/failed (%s)",
            method,
            fault.faultString,
        )
        return None

    # ODOO 19 returns {"id": ..., "name": ...}; older versions return the id
    if isinstance(result, dict):
        result = result.get("id")

    if isinstance(result, int) and result:
        return result

    return None


def _create_sign_template(client, document_name: str, pdf_bytes: bytes) -> dict:
    """Uploads the PDF and creates the sign.template for it.

    Returns {"template_id", "document_id"}; document_id is None on ODOO <= 18,
    where the attachment lives directly on the template.
    """
    pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
    template_fields = _get_model_fields(client, "sign.template")
    use_documents = "attachment_id" not in template_fields
    data_field = _get_attachment_data_field(client)

    filename = f"{document_name}.pdf"

    if use_documents:
        # ODOO 19+: official upload entrypoint (the one the web client calls);
        # it creates the attachment and the sign.document records internally
        # and returns {"id": template_id, "name": ...}
        template_id = _try_template_upload_method(
            client,
            "create_from_attachment_data",
            [[{"name": filename, data_field: pdf_b64}]],
        )

        if template_id is None:
            # manual fallback mirroring sign.document.create_from_attachment_data:
            # attachment from name + content, then document from attachment_id +
            # sequence. Never write the document's own binary field: on some
            # builds it maps to the attachment's *raw bytes*, so a base64
            # string would corrupt the stored PDF.
            attachment_id = _odoo_execute(
                client,
                model="ir.attachment",
                action="create",
                payload=[
                    {
                        "name": filename,
                        "type": "binary",
                        data_field: pdf_b64,
                        "mimetype": "application/pdf",
                    }
                ],
                options={},
            )

            template_id = _odoo_execute(
                client,
                model="sign.template",
                action="create",
                payload=[
                    {
                        "name": document_name,
                        "document_ids": [
                            [0, 0, {"attachment_id": attachment_id, "sequence": 1}]
                        ],
                    }
                ],
                options={},
            )

        return _resolve_template_document(client, template_id)

    # ODOO <= 18: official upload helper first, manual create as fallback
    template_id = _try_template_upload_method(
        client, "create_with_attachment_data", [filename, pdf_b64]
    )

    if template_id is None:
        attachment_id = _odoo_execute(
            client,
            model="ir.attachment",
            action="create",
            payload=[
                {
                    "name": filename,
                    "type": "binary",
                    data_field: pdf_b64,
                    "mimetype": "application/pdf",
                }
            ],
            options={},
        )

        template_id = _odoo_execute(
            client,
            model="sign.template",
            action="create",
            payload=[{"name": document_name, "attachment_id": attachment_id}],
            options={},
        )

    return {"template_id": template_id, "document_id": None}


def _resolve_template_document(client, template_id: int) -> dict:
    """Finds the sign.document created under the template (ODOO 19+ layout)."""
    document_ids = _odoo_execute(
        client,
        model="sign.document",
        action="search",
        payload=[[["template_id", "=", template_id]]],
        options={"limit": 1},
    )

    if not document_ids:
        raise ValidationError(
            "O documento não foi criado no serviço de assinatura digital.",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    return {"template_id": template_id, "document_id": document_ids[0]}


def _get_signer_partner_id(client, signer_name: str, signer_email: str) -> int:
    """Finds (or creates) the res.partner record for the signer."""
    partners = _odoo_execute(
        client,
        model="res.partner",
        action="search_read",
        payload=[[["email", "=", signer_email]]],
        options={"fields": ["id"], "limit": 1},
    )

    if partners:
        return partners[0]["id"]

    return _odoo_execute(
        client,
        model="res.partner",
        action="create",
        payload=[{"name": signer_name, "email": signer_email}],
        options={},
    )


def _get_signature_item_type_id(client) -> int:
    """Gets the sign.item.type id of the signature field."""
    type_ids = _odoo_execute(
        client,
        model="sign.item.type",
        action="search",
        payload=[[["item_type", "=", "signature"]]],
        options={"limit": 1},
    )

    if not type_ids:
        raise ValidationError(
            "Tipo de campo de assinatura não encontrado no serviço de assinatura digital.",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    return type_ids[0]


def _get_default_role_id(client) -> int:
    """Gets the default sign.item.role used for the single signer."""
    role_ids = _odoo_execute(
        client,
        model="sign.item.role",
        action="search",
        payload=[[]],
        options={"limit": 1, "order": "id asc"},
    )

    if not role_ids:
        raise ValidationError(
            "Papel de assinatura não encontrado no serviço de assinatura digital.",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    return role_ids[0]


def _build_sign_link(sign_request_id: int, access_token: str) -> str:
    """Builds the direct signing URL from a sign.request id and its access token."""
    base_url = Config.ODOO_API_URL.split("/xmlrpc")[0].rstrip("/")

    return f"{base_url}/sign/document/{sign_request_id}/{access_token}"


def _load_existing_sign_link(client, sign_request_id: int):
    """Rebuilds the signing link of an already created sign.request.

    Returns None when the request no longer resolves in ODOO (deleted or purged),
    which is what tells the caller the stored id went stale.

    Uses search_read rather than read on purpose: read on a purged id raises an
    XML-RPC Fault that _odoo_execute turns into a user-facing 400, while search_read
    simply comes back empty.
    """
    request_items = _odoo_execute(
        client,
        model="sign.request.item",
        action="search_read",
        payload=[[["sign_request_id", "=", sign_request_id]]],
        options={"fields": ["access_token"], "limit": 1},
    )

    if not request_items or not request_items[0].get("access_token"):
        return None

    return _build_sign_link(sign_request_id, request_items[0]["access_token"])


@has_permission(Permission.READ_NAV)
def request_signature(
    request_data: ClinicalNoteSignRequest, user_context: User
) -> dict:
    """Sends a clinical note PDF to ODOO Sign and returns the signing link."""
    signer_name = (request_data.signer_name or "").strip()
    signer_email = (request_data.signer_email or "").strip().lower()

    if not signer_name or not _EMAIL_REGEX.match(signer_email):
        raise ValidationError(
            "Signatário inválido: informe nome e e-mail válidos.",
            "errors.invalidParam",
            status.HTTP_400_BAD_REQUEST,
        )

    note = (
        db.session.query(ClinicalNotes)
        .options(undefer(ClinicalNotes.form), undefer(ClinicalNotes.template))
        .filter(ClinicalNotes.id == request_data.id)
        .first()
    )

    if not note:
        raise ValidationError(
            "Registro inexistente",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    if not note.text and not note.template:
        raise ValidationError(
            "Esta evolução não possui conteúdo para assinatura.",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    document_name = f"Evolução {note.id} - {note.date.strftime('%d/%m/%Y %H:%M')}"

    if request_data.preview:
        # debugging aid: return the generated PDF without contacting ODOO
        pdf_bytes, _, _ = _build_note_pdf(note=note)
        return {
            "preview": True,
            "filename": f"{document_name}.pdf",
            "pdf": base64.b64encode(pdf_bytes).decode("ascii"),
        }

    client = odoo_client.get_client(context="clinical notes sign service")
    if client is None:
        raise ValidationError(
            "Não foi possível conectar ao serviço de assinatura digital.",
            "errors.connectionTimeout",
            status.HTTP_504_GATEWAY_TIMEOUT,
        )

    # 0) this note was already sent for signature: rebuild the link for the stored
    # request instead of creating a new one (which would e-mail the signer again).
    # "force" is the explicit "sign again" action.
    if note.idSignRequest and not request_data.force:
        link = _load_existing_sign_link(client, note.idSignRequest)

        if not link:
            raise ValidationError(
                "A solicitação de assinatura anterior não existe mais no serviço de "
                'assinatura digital. Use "Assinar novamente" para gerar uma nova.',
                "errors.signRequestNotFound",
                status.HTTP_400_BAD_REQUEST,
            )

        return {
            "idSignRequest": note.idSignRequest,
            "link": link,
            "signerName": signer_name,
            "signerEmail": signer_email,
            "reused": True,
        }

    # only rendered when a request is actually going to be created
    pdf_bytes, sign_page, sign_pos_y = _build_note_pdf(note=note)

    # 1) + 2) upload the PDF and create the template pointing to it
    template = _create_sign_template(
        client, document_name=document_name, pdf_bytes=pdf_bytes
    )
    template_id = template["template_id"]
    document_id = template["document_id"]

    role_id = _get_default_role_id(client)

    # 3) signature field (position as fractions of the page); on ODOO 19+ the
    # field is anchored on the sign.document instead of the template
    item_values = {
        "type_id": _get_signature_item_type_id(client),
        "responsible_id": role_id,
        "required": True,
        "page": sign_page,
        "posX": _SIGN_ITEM_POS_X,
        "posY": sign_pos_y,
        "width": _SIGN_ITEM_WIDTH,
        "height": _SIGN_ITEM_HEIGHT,
    }

    if document_id is not None and "document_id" in _get_model_fields(
        client, "sign.item"
    ):
        item_values["document_id"] = document_id
    else:
        item_values["template_id"] = template_id

    _odoo_execute(
        client,
        model="sign.item",
        action="create",
        payload=[item_values],
        options={},
    )

    partner_id = _get_signer_partner_id(
        client, signer_name=signer_name, signer_email=signer_email
    )

    # 4) wizard: define the signer and trigger the e-mail
    wizard_id = _odoo_execute(
        client,
        model="sign.send.request",
        action="create",
        payload=[
            {
                "template_id": template_id,
                "signer_ids": [[0, 0, {"role_id": role_id, "partner_id": partner_id}]],
                "subject": f"Assinatura solicitada: {document_name}",
            }
        ],
        options={"context": {"default_template_id": template_id}},
    )

    _odoo_execute(
        client,
        model="sign.send.request",
        action="send_request",
        payload=[[wizard_id]],
        options={},
    )

    # 5) direct signing link built from the request item access token
    sign_requests = _odoo_execute(
        client,
        model="sign.request",
        action="search_read",
        payload=[[["template_id", "=", template_id]]],
        options={"fields": ["id"], "order": "id desc", "limit": 1},
    )

    if not sign_requests:
        raise ValidationError(
            "A solicitação de assinatura não foi criada no serviço de assinatura digital.",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    sign_request_id = sign_requests[0]["id"]

    # Store it as soon as it resolves: at this point the request exists in ODOO and
    # the signer e-mail has already gone out, so a failure further down must not lose
    # the id -- otherwise the next attempt would duplicate both.
    note.idSignRequest = sign_request_id
    note.update = datetime.today()
    note.user = user_context.id
    db.session.flush()

    # Same helper as the reuse branch, but a missing token means something different
    # here: the request was just created, so we still return 200 with link=None (the
    # historical behaviour) instead of the 400 the reuse branch raises for a stale id.
    link = _load_existing_sign_link(client, sign_request_id)

    return {
        "idSignRequest": sign_request_id,
        "link": link,
        "signerName": signer_name,
        "signerEmail": signer_email,
        "reused": False,
    }
