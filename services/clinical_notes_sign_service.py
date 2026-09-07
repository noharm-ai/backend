"""Service: digital signature of clinical notes.

Orchestrates the note validation, the PDF rendering
(clinical_notes_pdf_service) and the ODOO Sign integration
(odoo_sign_service), and keeps the resulting sign.request id on the note.
"""

import base64
import re
from datetime import datetime

from sqlalchemy.orm import undefer

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.main import User, db
from models.notes import ClinicalNotes
from models.requests.clinical_notes_request import ClinicalNoteSignRequest
from services import clinical_notes_pdf_service, odoo_client, odoo_sign_service
from utils import status

_EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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
        pdf_bytes, _, _ = clinical_notes_pdf_service.build_note_pdf(note=note)
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

    # this note was already sent for signature: rebuild the link for the stored
    # request instead of creating a new one (which would e-mail the signer again).
    # "force" is the explicit "sign again" action.
    if note.idSignRequest and not request_data.force:
        link = odoo_sign_service.load_existing_sign_link(client, note.idSignRequest)

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
    pdf_bytes, sign_page, sign_pos_y = clinical_notes_pdf_service.build_note_pdf(
        note=note
    )

    sign_request_id = odoo_sign_service.create_signature_request(
        client,
        document_name=document_name,
        pdf_bytes=pdf_bytes,
        sign_page=sign_page,
        sign_pos_y=sign_pos_y,
        signer_name=signer_name,
        signer_email=signer_email,
    )

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
    link = odoo_sign_service.load_existing_sign_link(client, sign_request_id)

    return {
        "idSignRequest": sign_request_id,
        "link": link,
        "signerName": signer_name,
        "signerEmail": signer_email,
        "reused": False,
    }
