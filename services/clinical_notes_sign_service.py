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
- ODOO 19+: sign.template holds sign.document records (document_ids), the PDF
  lives on sign.document.attachment_id and sign.item points to document_id.
"""

import base64
import re
import xmlrpc.client
from html.parser import HTMLParser

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

# signature field footprint (fractions of the page, as expected by sign.item)
_SIGN_ITEM_POS_X = 0.35
_SIGN_ITEM_WIDTH = 0.3
_SIGN_ITEM_HEIGHT = 0.05


class _HtmlTextExtractor(HTMLParser):
    """Converts the clinical note HTML into plain text suitable for the PDF."""

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

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_anchor = False

    def handle_starttag(self, tag, attrs):
        """Handles opening tags: line breaks and annotation close buttons."""
        if tag == "br":
            self._parts.append("\n")
        elif tag == "a":
            # annotation close buttons ("X") must not leak into the document
            attrs_dict = dict(attrs)
            if "close-btn" in (attrs_dict.get("class") or ""):
                self._skip_anchor = True

    def handle_endtag(self, tag):
        """Handles closing tags: block tags become line breaks."""
        if tag == "a":
            self._skip_anchor = False
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data):
        """Collects text content outside skipped elements."""
        if not self._skip_anchor:
            self._parts.append(data)

    def get_text(self) -> str:
        """Returns the extracted text with collapsed blank lines."""
        text = "".join(self._parts)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def _html_to_text(html: str) -> str:
    """Converts an HTML fragment into plain text."""
    if not html:
        return ""

    parser = _HtmlTextExtractor()
    parser.feed(html)
    parser.close()

    return parser.get_text()


def _to_latin1(text: str) -> str:
    """Coerces text to latin-1 (PDF core fonts), replacing unsupported chars."""
    return (text or "").encode("latin-1", "replace").decode("latin-1")


def _format_form_value(value) -> str:
    """Formats a custom form answer the same way the frontend renders it."""
    if value is None or value == "":
        return "Sem resposta"

    if isinstance(value, list):
        return ", ".join([str(item) for item in value])

    if isinstance(value, dict):
        return str(value.get("label", ""))

    return str(value)


def _get_note_body(note: ClinicalNotes) -> str:
    """Extracts the printable body of a clinical note (free text or custom form)."""
    if note.text:
        return _html_to_text(note.text)

    if note.template:
        lines = []
        form = note.form or {}

        for group in note.template:
            lines.append(str(group.get("group", "")))

            for question in group.get("questions", []):
                value = _format_form_value(form.get(str(question.get("id"))))
                lines.append(f"{question.get('label', '')}: {_html_to_text(value)}")

            lines.append("")

        return "\n".join(lines).strip()

    return ""


def _get_institution_header() -> str:
    """Gets the institution header configured in the nav-header memory record."""
    memory = db.session.query(Memory).filter(Memory.kind == "nav-header").first()

    if memory and memory.value:
        return _html_to_text(memory.value.get("header", ""))

    return ""


def _build_note_pdf(note: ClinicalNotes) -> tuple[bytes, int, float]:
    """Builds the clinical note PDF.

    Returns the PDF bytes, the page where the signature field must be placed
    and its vertical position as a fraction (0-1) of the page height.
    """
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    institution_header = _get_institution_header()
    if institution_header:
        pdf.set_font("helvetica", size=9)
        pdf.multi_cell(w=0, h=4.5, text=_to_latin1(institution_header), align="C")
        pdf.ln(2)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(6)

    note_header = (
        f"{note.date.strftime('%d/%m/%Y %H:%M')} - {note.prescriber or ''}".strip(" -")
    )
    pdf.set_font("helvetica", style="B", size=11)
    pdf.multi_cell(w=0, h=6, text=_to_latin1(note_header))
    pdf.ln(4)

    pdf.set_font("helvetica", size=10)
    pdf.multi_cell(w=0, h=5, text=_to_latin1(_get_note_body(note)))

    # dedicated signature area: keep it on the page where the content ended
    # (or on a new one when there is no room left)
    pdf.ln(14)
    if pdf.get_y() > _A4_HEIGHT_MM - 55:
        pdf.add_page()
        pdf.ln(10)

    sign_page = pdf.page_no()
    sign_pos_y = pdf.get_y() / _A4_HEIGHT_MM

    pdf.ln(22)
    line_start = pdf.w * _SIGN_ITEM_POS_X
    line_end = pdf.w * (_SIGN_ITEM_POS_X + _SIGN_ITEM_WIDTH)
    pdf.line(line_start, pdf.get_y(), line_end, pdf.get_y())
    pdf.ln(2)
    pdf.set_font("helvetica", size=8)
    pdf.multi_cell(w=0, h=4, text=_to_latin1(note.prescriber or ""), align="C")

    return bytes(pdf.output()), sign_page, sign_pos_y


def _odoo_execute(client, **kwargs):
    """Executes an ODOO call and converts a timeout (None) into a 504 error."""
    result = client(**kwargs)

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


def _create_template_with_helper(client, document_name: str, pdf_b64: str):
    """Tries sign.template.create_with_attachment_data (the helper used by the
    ODOO UI upload, which handles attachment linking and PDF processing).

    Returns the template id, or None when the helper is unavailable or
    rejected the file (some versions return 0 instead of raising).
    """
    try:
        template_id = client(
            model="sign.template",
            action="create_with_attachment_data",
            payload=[f"{document_name}.pdf", pdf_b64],
            options={},
        )
    except xmlrpc.client.Fault as fault:
        logger.backend_logger.warning(
            "ODOO Sign: create_with_attachment_data unavailable/failed (%s)",
            fault.faultString,
        )
        return None

    return template_id or None


def _create_sign_template(client, document_name: str, pdf_bytes: bytes) -> dict:
    """Uploads the PDF and creates the sign.template for it.

    Returns {"template_id", "document_id"}; document_id is None on ODOO <= 18,
    where the attachment lives directly on the template.
    """
    pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
    template_fields = _get_model_fields(client, "sign.template")
    use_documents = "attachment_id" not in template_fields

    template_id = _create_template_with_helper(
        client, document_name=document_name, pdf_b64=pdf_b64
    )

    if template_id is None:
        # manual fallback: unattached upload (linked afterwards by ODOO),
        # exactly like the web client does before creating the template
        attachment_id = _odoo_execute(
            client,
            model="ir.attachment",
            action="create",
            payload=[
                {
                    "name": f"{document_name}.pdf",
                    "type": "binary",
                    "datas": pdf_b64,
                    "mimetype": "application/pdf",
                }
            ],
            options={},
        )

        if use_documents:
            template_id = _odoo_execute(
                client,
                model="sign.template",
                action="create",
                payload=[
                    {
                        "name": document_name,
                        "document_ids": [[0, 0, {"attachment_id": attachment_id}]],
                    }
                ],
                options={},
            )
        else:
            template_id = _odoo_execute(
                client,
                model="sign.template",
                action="create",
                payload=[{"name": document_name, "attachment_id": attachment_id}],
                options={},
            )

    if not use_documents:
        return {"template_id": template_id, "document_id": None}

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

    pdf_bytes, sign_page, sign_pos_y = _build_note_pdf(note=note)

    document_name = f"Evolução {note.id} - {note.date.strftime('%d/%m/%Y %H:%M')}"

    if request_data.preview:
        # debugging aid: return the generated PDF without contacting ODOO
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

    request_items = _odoo_execute(
        client,
        model="sign.request.item",
        action="search_read",
        payload=[[["sign_request_id", "=", sign_request_id]]],
        options={"fields": ["access_token"], "limit": 1},
    )

    link = None
    if request_items and request_items[0].get("access_token"):
        base_url = Config.ODOO_API_URL.split("/xmlrpc")[0].rstrip("/")
        link = (
            f"{base_url}/sign/document/{sign_request_id}/"
            f"{request_items[0]['access_token']}"
        )

    return {
        "idSignRequest": sign_request_id,
        "link": link,
        "signerName": signer_name,
        "signerEmail": signer_email,
    }
