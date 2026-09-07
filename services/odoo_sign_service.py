"""Service: digital signature of documents through the ODOO Sign module.

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
import xmlrpc.client

from config import Config
from exception.validation_error import ValidationError
from utils import logger, status

# signature field footprint (fractions of the page, as expected by sign.item).
# posX left-aligns the field with the 10mm left margin FPDF gives the text.
_SIGN_ITEM_POS_X = 10 / 210
_SIGN_ITEM_WIDTH = 0.3
_SIGN_ITEM_HEIGHT = 0.05


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


def _create_signature_field(
    client, template: dict, role_id: int, page: int, pos_y: float
) -> None:
    """Creates the sign.item that places the signature field on the document.

    On ODOO 19+ the field is anchored on the sign.document instead of the
    template.
    """
    item_values = {
        "type_id": _get_signature_item_type_id(client),
        "responsible_id": role_id,
        "required": True,
        "page": page,
        "posX": _SIGN_ITEM_POS_X,
        "posY": pos_y,
        "width": _SIGN_ITEM_WIDTH,
        "height": _SIGN_ITEM_HEIGHT,
    }

    document_id = template["document_id"]

    if document_id is not None and "document_id" in _get_model_fields(
        client, "sign.item"
    ):
        item_values["document_id"] = document_id
    else:
        item_values["template_id"] = template["template_id"]

    _odoo_execute(
        client,
        model="sign.item",
        action="create",
        payload=[item_values],
        options={},
    )


def _send_sign_request(
    client, template_id: int, document_name: str, role_id: int, partner_id: int
) -> int:
    """Runs the sign.send.request wizard (which e-mails the signer) and returns
    the id of the sign.request it created."""
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

    return sign_requests[0]["id"]


def _build_sign_link(sign_request_id: int, access_token: str) -> str:
    """Builds the direct signing URL from a sign.request id and its access token."""
    base_url = Config.ODOO_API_URL.split("/xmlrpc")[0].rstrip("/")

    return f"{base_url}/sign/document/{sign_request_id}/{access_token}"


def create_signature_request(
    client,
    document_name: str,
    pdf_bytes: bytes,
    sign_page: int,
    sign_pos_y: float,
    signer_name: str,
    signer_email: str,
) -> int:
    """Uploads the PDF, places the signature field and requests the signature.

    Returns the id of the created sign.request. The signer e-mail has already
    been sent by the time this returns, so the caller must not lose the id.
    """
    # 1) + 2) upload the PDF and create the template pointing to it
    template = _create_sign_template(
        client, document_name=document_name, pdf_bytes=pdf_bytes
    )

    role_id = _get_default_role_id(client)

    # 3) signature field (position as fractions of the page)
    _create_signature_field(
        client, template=template, role_id=role_id, page=sign_page, pos_y=sign_pos_y
    )

    partner_id = _get_signer_partner_id(
        client, signer_name=signer_name, signer_email=signer_email
    )

    # 4) wizard: define the signer and trigger the e-mail
    return _send_sign_request(
        client,
        template_id=template["template_id"],
        document_name=document_name,
        role_id=role_id,
        partner_id=partner_id,
    )


def load_existing_sign_link(client, sign_request_id: int):
    """Rebuilds the signing link of an already created sign.request.

    Returns None when the request no longer resolves in ODOO (deleted or purged),
    which is what tells the caller the stored id went stale.

    Uses search_read rather than read on purpose: read on a purged id raises an
    XML-RPC Fault that _odoo_execute turns into a user-facing 400, while search_read
    simply comes back empty.
    """
    # 5) direct signing link built from the request item access token
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
