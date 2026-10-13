"""Unit tests for services.odoo_sign_service — digital signature through ODOO Sign.

The service drives the ODOO Sign module over XML-RPC to have a clinical
document signed: it uploads the PDF, creates a sign.template, places the
signature field, runs the sign.send.request wizard (which e-mails the signer)
and later rebuilds the direct signing link from the request's access token.

Two ODOO layouts are supported and detected at runtime through ``fields_get``:

* ODOO <= 18 — the PDF hangs directly on ``sign.template.attachment_id``, the
  attachment content goes in ``datas`` and ``sign.item`` points to the
  template;
* ODOO 19+ — the template holds ``sign.document`` records, ``datas`` is gone
  (content goes in ``raw``) and ``sign.item`` points to the document.

What these tests pin down:

* ODOO errors are translated: a timeout (``None``) becomes a 504, a business
  fault (code 2) a 400 carrying ODOO's message, any other fault propagates;
* each layout uploads through its official helper and, when the helper is
  missing or rejects the file, falls back to creating the attachment and the
  template by hand — writing the content to the field that layout supports;
* the signature field is anchored to the document on ODOO 19+ and to the
  template otherwise;
* the signer partner is reused when one exists for the e-mail;
* missing records (document, field type, role, sign request) are reported as
  400s instead of crashing on an empty list;
* the signing link is built from the ODOO base URL, and an unresolvable
  request yields ``None`` so the caller knows its stored id went stale.

ODOO itself is replaced by ``FakeOdoo``, a callable with the same keyword
signature as the real client that answers from a ``(model, action)`` table and
records every call.
"""

import base64
import xmlrpc.client
from unittest.mock import patch

import pytest

from exception.validation_error import ValidationError
from services import odoo_sign_service
from utils import status

PDF_BYTES = b"%PDF-1.4 fake document"
PDF_B64 = base64.b64encode(PDF_BYTES).decode("ascii")
DOC_NAME = "Evolucao Farmaceutica"
FILENAME = f"{DOC_NAME}.pdf"

SIGNER_NAME = "Fulano Beltrano"
SIGNER_EMAIL = "fulano@example.com"

TEMPLATE_ID = 31
DOCUMENT_ID = 41
ATTACHMENT_ID = 51
ROLE_ID = 61
ITEM_TYPE_ID = 71
PARTNER_ID = 81
WIZARD_ID = 91
SIGN_REQUEST_ID = 101


class FakeOdoo:
    """Stand-in for the ODOO XML-RPC client used by the service.

    ``responses`` maps ``(model, action)`` to the value to return. A value that
    is an exception is raised instead, and a callable is called with the
    payload so a test can vary the answer. Any call not in the table fails the
    test, so the service can't silently hit an endpoint the test didn't expect.
    """

    def __init__(self, responses: dict):
        """Keep the answer table and start an empty call log."""
        self.responses = responses
        self.calls = []

    def __call__(self, model, action, payload, options):
        """Record the call and answer it from the table."""
        self.calls.append(
            {"model": model, "action": action, "payload": payload, "options": options}
        )

        if (model, action) not in self.responses:
            raise AssertionError(f"unexpected ODOO call {model}.{action}")

        answer = self.responses[(model, action)]
        if isinstance(answer, BaseException):
            raise answer
        if callable(answer):
            return answer(payload)
        return answer

    def calls_to(self, model, action):
        """Return the recorded calls for one ``model.action``."""
        return [c for c in self.calls if c["model"] == model and c["action"] == action]

    def sequence(self):
        """Return the ``model.action`` names in the order they were called."""
        return [f"{c['model']}.{c['action']}" for c in self.calls]


def _fields(*names):
    """Build a ``fields_get`` answer exposing the given field names."""
    return {name: {"type": "char"} for name in names}


def _odoo18_responses(overrides=None):
    """Answer table of an ODOO <= 18 server where every step succeeds."""
    responses = {
        ("sign.template", "fields_get"): _fields("name", "attachment_id"),
        ("ir.attachment", "fields_get"): _fields("name", "datas", "raw"),
        ("sign.template", "create_with_attachment_data"): TEMPLATE_ID,
        ("sign.item.role", "search"): [ROLE_ID],
        ("sign.item.type", "search"): [ITEM_TYPE_ID],
        ("sign.item", "create"): 1,
        ("res.partner", "search_read"): [{"id": PARTNER_ID}],
        ("sign.send.request", "create"): WIZARD_ID,
        ("sign.send.request", "send_request"): True,
        ("sign.request", "search_read"): [{"id": SIGN_REQUEST_ID}],
    }
    responses.update(overrides or {})
    return responses


def _odoo19_responses(overrides=None):
    """Answer table of an ODOO 19+ server where every step succeeds."""
    responses = {
        ("sign.template", "fields_get"): _fields("name", "document_ids"),
        ("ir.attachment", "fields_get"): _fields("name", "raw"),
        ("sign.template", "create_from_attachment_data"): {
            "id": TEMPLATE_ID,
            "name": FILENAME,
        },
        ("sign.document", "search"): [DOCUMENT_ID],
        ("sign.item", "fields_get"): _fields("document_id", "type_id"),
        ("sign.item.role", "search"): [ROLE_ID],
        ("sign.item.type", "search"): [ITEM_TYPE_ID],
        ("sign.item", "create"): 1,
        ("res.partner", "search_read"): [{"id": PARTNER_ID}],
        ("sign.send.request", "create"): WIZARD_ID,
        ("sign.send.request", "send_request"): True,
        ("sign.request", "search_read"): [{"id": SIGN_REQUEST_ID}],
    }
    responses.update(overrides or {})
    return responses


def _business_fault(message="Documento inválido"):
    """An ODOO UserError as it arrives over XML-RPC (fault code 2)."""
    return xmlrpc.client.Fault(2, message)


# --- _odoo_execute: error translation ---------------------------------------


def test_execute_returns_the_odoo_result():
    """A successful call hands back ODOO's answer untouched."""
    client = FakeOdoo({("res.partner", "search"): [1, 2]})

    result = odoo_sign_service._odoo_execute(
        client, model="res.partner", action="search", payload=[[]], options={}
    )

    assert result == [1, 2]


def test_execute_turns_a_timeout_into_504():
    """The client returns None on timeout; that surfaces as a gateway timeout."""
    client = FakeOdoo({("res.partner", "search"): None})

    with pytest.raises(ValidationError) as exc:
        odoo_sign_service._odoo_execute(
            client, model="res.partner", action="search", payload=[[]], options={}
        )

    assert exc.value.httpStatus == status.HTTP_504_GATEWAY_TIMEOUT
    assert exc.value.code == "errors.connectionTimeout"


def test_execute_turns_a_business_fault_into_400_with_odoo_message():
    """A UserError (fault code 2) reaches the user as a 400 with ODOO's text."""
    client = FakeOdoo({("sign.template", "create"): _business_fault("PDF corrompido")})

    with pytest.raises(ValidationError) as exc:
        odoo_sign_service._odoo_execute(
            client, model="sign.template", action="create", payload=[{}], options={}
        )

    assert exc.value.httpStatus == status.HTTP_400_BAD_REQUEST
    assert exc.value.code == "errors.invalidParam"
    assert "PDF corrompido" in str(exc.value)


def test_execute_propagates_other_faults():
    """Faults other than business errors are not masked as a 400."""
    fault = xmlrpc.client.Fault(1, "Traceback: internal error")
    client = FakeOdoo({("sign.template", "create"): fault})

    with pytest.raises(xmlrpc.client.Fault) as exc:
        odoo_sign_service._odoo_execute(
            client, model="sign.template", action="create", payload=[{}], options={}
        )

    assert exc.value.faultCode == 1


def test_execute_keeps_falsy_non_none_results():
    """Only None means timeout: an empty list or 0 is a valid answer."""
    client = FakeOdoo({("sign.item.type", "search"): []})

    result = odoo_sign_service._odoo_execute(
        client, model="sign.item.type", action="search", payload=[[]], options={}
    )

    assert result == []


# --- version introspection ----------------------------------------------------


def test_attachment_field_is_datas_when_odoo_still_has_it():
    """ODOO <= 18 keeps the content in ``datas``."""
    client = FakeOdoo({("ir.attachment", "fields_get"): _fields("datas", "raw")})

    assert odoo_sign_service._get_attachment_data_field(client) == "datas"


def test_attachment_field_is_raw_on_odoo_19():
    """ODOO 19 dropped ``datas``; writing it would create an empty attachment."""
    client = FakeOdoo({("ir.attachment", "fields_get"): _fields("name", "raw")})

    assert odoo_sign_service._get_attachment_data_field(client) == "raw"


# --- _try_template_upload_method --------------------------------------------


@pytest.mark.parametrize(
    "answer, expected",
    [
        (TEMPLATE_ID, TEMPLATE_ID),
        ({"id": TEMPLATE_ID, "name": FILENAME}, TEMPLATE_ID),
        (0, None),
        (False, None),
        ({"id": False}, None),
        ([TEMPLATE_ID], None),
    ],
    ids=["int-id", "dict-id", "zero", "false", "dict-without-id", "list"],
)
def test_upload_method_answer_normalization(answer, expected):
    """Only a positive int id (bare or inside a dict) counts as a created template."""
    client = FakeOdoo({("sign.template", "create_with_attachment_data"): answer})

    result = odoo_sign_service._try_template_upload_method(
        client, "create_with_attachment_data", [FILENAME, PDF_B64]
    )

    assert result == expected


def test_upload_method_fault_means_unavailable():
    """A fault from the helper is swallowed so the caller can fall back."""
    client = FakeOdoo(
        {
            ("sign.template", "create_from_attachment_data"): xmlrpc.client.Fault(
                1, "method does not exist"
            )
        }
    )

    result = odoo_sign_service._try_template_upload_method(
        client, "create_from_attachment_data", [[]]
    )

    assert result is None


# --- _create_sign_template: ODOO <= 18 ---------------------------------------


def test_odoo18_template_uses_official_upload_helper():
    """The helper receives the filename and the base64 content; no manual create."""
    client = FakeOdoo(_odoo18_responses())

    template = odoo_sign_service._create_sign_template(
        client, document_name=DOC_NAME, pdf_bytes=PDF_BYTES
    )

    assert template == {"template_id": TEMPLATE_ID, "document_id": None}
    (upload,) = client.calls_to("sign.template", "create_with_attachment_data")
    assert upload["payload"] == [FILENAME, PDF_B64]
    assert client.calls_to("ir.attachment", "create") == []
    assert client.calls_to("sign.template", "create") == []


def test_odoo18_template_falls_back_to_manual_create():
    """When the helper rejects the file, attachment and template are created by hand."""
    client = FakeOdoo(
        _odoo18_responses(
            {
                ("sign.template", "create_with_attachment_data"): 0,
                ("ir.attachment", "create"): ATTACHMENT_ID,
                ("sign.template", "create"): TEMPLATE_ID,
            }
        )
    )

    template = odoo_sign_service._create_sign_template(
        client, document_name=DOC_NAME, pdf_bytes=PDF_BYTES
    )

    assert template == {"template_id": TEMPLATE_ID, "document_id": None}

    (attachment,) = client.calls_to("ir.attachment", "create")
    assert attachment["payload"] == [
        {
            "name": FILENAME,
            "type": "binary",
            "datas": PDF_B64,
            "mimetype": "application/pdf",
        }
    ]

    (template_create,) = client.calls_to("sign.template", "create")
    assert template_create["payload"] == [
        {"name": DOC_NAME, "attachment_id": ATTACHMENT_ID}
    ]


# --- _create_sign_template: ODOO 19+ -----------------------------------------


def test_odoo19_template_uses_official_upload_and_resolves_document():
    """The helper gets ``raw`` content and the template's document is looked up."""
    client = FakeOdoo(_odoo19_responses())

    template = odoo_sign_service._create_sign_template(
        client, document_name=DOC_NAME, pdf_bytes=PDF_BYTES
    )

    assert template == {"template_id": TEMPLATE_ID, "document_id": DOCUMENT_ID}

    (upload,) = client.calls_to("sign.template", "create_from_attachment_data")
    assert upload["payload"] == [[{"name": FILENAME, "raw": PDF_B64}]]

    (search,) = client.calls_to("sign.document", "search")
    assert search["payload"] == [[["template_id", "=", TEMPLATE_ID]]]
    assert client.calls_to("ir.attachment", "create") == []


def test_odoo19_template_falls_back_to_document_ids():
    """Without the helper, the template is built with a sign.document command."""
    client = FakeOdoo(
        _odoo19_responses(
            {
                ("sign.template", "create_from_attachment_data"): xmlrpc.client.Fault(
                    1, "method does not exist"
                ),
                ("ir.attachment", "create"): ATTACHMENT_ID,
                ("sign.template", "create"): TEMPLATE_ID,
            }
        )
    )

    template = odoo_sign_service._create_sign_template(
        client, document_name=DOC_NAME, pdf_bytes=PDF_BYTES
    )

    assert template == {"template_id": TEMPLATE_ID, "document_id": DOCUMENT_ID}

    (attachment,) = client.calls_to("ir.attachment", "create")
    attachment_values = attachment["payload"][0]
    assert attachment_values["raw"] == PDF_B64
    assert "datas" not in attachment_values

    (template_create,) = client.calls_to("sign.template", "create")
    assert template_create["payload"] == [
        {
            "name": DOC_NAME,
            "document_ids": [[0, 0, {"attachment_id": ATTACHMENT_ID, "sequence": 1}]],
        }
    ]


def test_odoo19_template_without_document_is_rejected():
    """A template that ended up without a sign.document is reported, not used."""
    client = FakeOdoo(_odoo19_responses({("sign.document", "search"): []}))

    with pytest.raises(ValidationError) as exc:
        odoo_sign_service._create_sign_template(
            client, document_name=DOC_NAME, pdf_bytes=PDF_BYTES
        )

    assert exc.value.httpStatus == status.HTTP_400_BAD_REQUEST
    assert exc.value.code == "errors.invalidRecord"


# --- signer, role and field type lookups -------------------------------------


def test_signer_partner_is_reused_when_email_exists():
    """An existing partner for the e-mail is reused; nothing is created."""
    client = FakeOdoo({("res.partner", "search_read"): [{"id": PARTNER_ID}]})

    partner_id = odoo_sign_service._get_signer_partner_id(
        client, signer_name=SIGNER_NAME, signer_email=SIGNER_EMAIL
    )

    assert partner_id == PARTNER_ID
    (search,) = client.calls_to("res.partner", "search_read")
    assert search["payload"] == [[["email", "=", SIGNER_EMAIL]]]


def test_signer_partner_is_created_when_missing():
    """Without a partner for the e-mail, one is created with the signer's name."""
    client = FakeOdoo(
        {
            ("res.partner", "search_read"): [],
            ("res.partner", "create"): PARTNER_ID,
        }
    )

    partner_id = odoo_sign_service._get_signer_partner_id(
        client, signer_name=SIGNER_NAME, signer_email=SIGNER_EMAIL
    )

    assert partner_id == PARTNER_ID
    (create,) = client.calls_to("res.partner", "create")
    assert create["payload"] == [{"name": SIGNER_NAME, "email": SIGNER_EMAIL}]


def test_missing_signature_item_type_is_rejected():
    """A Sign module without the signature field type can't place the field."""
    client = FakeOdoo({("sign.item.type", "search"): []})

    with pytest.raises(ValidationError) as exc:
        odoo_sign_service._get_signature_item_type_id(client)

    assert exc.value.code == "errors.invalidRecord"


def test_missing_role_is_rejected():
    """A Sign module without any role can't assign the signer."""
    client = FakeOdoo({("sign.item.role", "search"): []})

    with pytest.raises(ValidationError) as exc:
        odoo_sign_service._get_default_role_id(client)

    assert exc.value.code == "errors.invalidRecord"


def test_default_role_is_the_first_by_id():
    """The single signer takes the lowest-id role."""
    client = FakeOdoo({("sign.item.role", "search"): [ROLE_ID, ROLE_ID + 1]})

    assert odoo_sign_service._get_default_role_id(client) == ROLE_ID
    (search,) = client.calls_to("sign.item.role", "search")
    assert search["options"]["order"] == "id asc"


# --- _create_signature_field --------------------------------------------------


def test_signature_field_is_anchored_to_document_on_odoo19():
    """With a document and a ``document_id`` field, the item points to the document."""
    client = FakeOdoo(_odoo19_responses())

    odoo_sign_service._create_signature_field(
        client,
        template={"template_id": TEMPLATE_ID, "document_id": DOCUMENT_ID},
        role_id=ROLE_ID,
        page=2,
        pos_y=0.8,
    )

    (create,) = client.calls_to("sign.item", "create")
    values = create["payload"][0]
    assert values["document_id"] == DOCUMENT_ID
    assert "template_id" not in values
    assert values["type_id"] == ITEM_TYPE_ID
    assert values["responsible_id"] == ROLE_ID
    assert values["required"] is True
    assert values["page"] == 2
    assert values["posY"] == 0.8
    assert values["posX"] == pytest.approx(10 / 210)
    assert values["width"] == pytest.approx(0.3)
    assert values["height"] == pytest.approx(0.05)


def test_signature_field_is_anchored_to_template_on_odoo18():
    """Without a document the item points to the template; no field lookup is needed."""
    client = FakeOdoo(_odoo18_responses())

    odoo_sign_service._create_signature_field(
        client,
        template={"template_id": TEMPLATE_ID, "document_id": None},
        role_id=ROLE_ID,
        page=1,
        pos_y=0.5,
    )

    (create,) = client.calls_to("sign.item", "create")
    values = create["payload"][0]
    assert values["template_id"] == TEMPLATE_ID
    assert "document_id" not in values
    assert client.calls_to("sign.item", "fields_get") == []


def test_signature_field_falls_back_to_template_when_item_has_no_document_field():
    """A document id is ignored when sign.item can't reference documents."""
    client = FakeOdoo(
        _odoo19_responses({("sign.item", "fields_get"): _fields("template_id")})
    )

    odoo_sign_service._create_signature_field(
        client,
        template={"template_id": TEMPLATE_ID, "document_id": DOCUMENT_ID},
        role_id=ROLE_ID,
        page=1,
        pos_y=0.5,
    )

    (create,) = client.calls_to("sign.item", "create")
    values = create["payload"][0]
    assert values["template_id"] == TEMPLATE_ID
    assert "document_id" not in values


# --- _send_sign_request -------------------------------------------------------


def test_send_request_runs_the_wizard_and_returns_the_request_id():
    """The wizard is created for the signer, sent, and the newest request returned."""
    client = FakeOdoo(_odoo18_responses())

    request_id = odoo_sign_service._send_sign_request(
        client,
        template_id=TEMPLATE_ID,
        document_name=DOC_NAME,
        role_id=ROLE_ID,
        partner_id=PARTNER_ID,
    )

    assert request_id == SIGN_REQUEST_ID

    (wizard,) = client.calls_to("sign.send.request", "create")
    assert wizard["payload"] == [
        {
            "template_id": TEMPLATE_ID,
            "signer_ids": [[0, 0, {"role_id": ROLE_ID, "partner_id": PARTNER_ID}]],
            "subject": f"Assinatura solicitada: {DOC_NAME}",
        }
    ]
    assert wizard["options"] == {"context": {"default_template_id": TEMPLATE_ID}}

    (send,) = client.calls_to("sign.send.request", "send_request")
    assert send["payload"] == [[WIZARD_ID]]

    (lookup,) = client.calls_to("sign.request", "search_read")
    assert lookup["payload"] == [[["template_id", "=", TEMPLATE_ID]]]
    assert lookup["options"]["order"] == "id desc"


def test_send_request_without_created_request_is_rejected():
    """If the wizard created no sign.request, the caller gets a 400."""
    client = FakeOdoo(_odoo18_responses({("sign.request", "search_read"): []}))

    with pytest.raises(ValidationError) as exc:
        odoo_sign_service._send_sign_request(
            client,
            template_id=TEMPLATE_ID,
            document_name=DOC_NAME,
            role_id=ROLE_ID,
            partner_id=PARTNER_ID,
        )

    assert exc.value.code == "errors.invalidRecord"


# --- create_signature_request: whole flow ------------------------------------


def test_full_flow_on_odoo18():
    """Upload, field, signer and wizard run in order and the request id comes back."""
    client = FakeOdoo(_odoo18_responses())

    request_id = odoo_sign_service.create_signature_request(
        client,
        document_name=DOC_NAME,
        pdf_bytes=PDF_BYTES,
        sign_page=1,
        sign_pos_y=0.7,
        signer_name=SIGNER_NAME,
        signer_email=SIGNER_EMAIL,
    )

    assert request_id == SIGN_REQUEST_ID
    assert client.sequence() == [
        "sign.template.fields_get",
        "ir.attachment.fields_get",
        "sign.template.create_with_attachment_data",
        "sign.item.role.search",
        "sign.item.type.search",
        "sign.item.create",
        "res.partner.search_read",
        "sign.send.request.create",
        "sign.send.request.send_request",
        "sign.request.search_read",
    ]


def test_full_flow_on_odoo19():
    """On ODOO 19 the document is resolved and the field anchored to it."""
    client = FakeOdoo(_odoo19_responses())

    request_id = odoo_sign_service.create_signature_request(
        client,
        document_name=DOC_NAME,
        pdf_bytes=PDF_BYTES,
        sign_page=3,
        sign_pos_y=0.25,
        signer_name=SIGNER_NAME,
        signer_email=SIGNER_EMAIL,
    )

    assert request_id == SIGN_REQUEST_ID
    (create,) = client.calls_to("sign.item", "create")
    assert create["payload"][0]["document_id"] == DOCUMENT_ID
    assert create["payload"][0]["page"] == 3
    (wizard,) = client.calls_to("sign.send.request", "create")
    assert wizard["payload"][0]["template_id"] == TEMPLATE_ID


def test_full_flow_stops_before_emailing_when_role_is_missing():
    """A setup error aborts the flow before the signer is e-mailed."""
    client = FakeOdoo(_odoo18_responses({("sign.item.role", "search"): []}))

    with pytest.raises(ValidationError):
        odoo_sign_service.create_signature_request(
            client,
            document_name=DOC_NAME,
            pdf_bytes=PDF_BYTES,
            sign_page=1,
            sign_pos_y=0.7,
            signer_name=SIGNER_NAME,
            signer_email=SIGNER_EMAIL,
        )

    assert client.calls_to("sign.send.request", "create") == []
    assert client.calls_to("sign.send.request", "send_request") == []


# --- signing link -------------------------------------------------------------


@pytest.mark.parametrize(
    "api_url",
    [
        "https://odoo.example.com/xmlrpc/2/object",
        "https://odoo.example.com/",
        "https://odoo.example.com",
    ],
)
def test_sign_link_is_built_from_the_odoo_base_url(api_url):
    """The XML-RPC path and trailing slash are stripped from the configured URL."""
    with patch.object(odoo_sign_service.Config, "ODOO_API_URL", api_url):
        link = odoo_sign_service._build_sign_link(SIGN_REQUEST_ID, "tok123")

    assert link == f"https://odoo.example.com/sign/document/{SIGN_REQUEST_ID}/tok123"


def test_existing_sign_link_is_rebuilt_from_access_token():
    """The request item's access token yields the direct signing link."""
    client = FakeOdoo(
        {("sign.request.item", "search_read"): [{"id": 1, "access_token": "abc"}]}
    )

    with patch.object(
        odoo_sign_service.Config,
        "ODOO_API_URL",
        "https://odoo.example.com/xmlrpc/2/object",
    ):
        link = odoo_sign_service.load_existing_sign_link(client, SIGN_REQUEST_ID)

    assert link == f"https://odoo.example.com/sign/document/{SIGN_REQUEST_ID}/abc"
    (search,) = client.calls_to("sign.request.item", "search_read")
    assert search["payload"] == [[["sign_request_id", "=", SIGN_REQUEST_ID]]]


@pytest.mark.parametrize(
    "items",
    [[], [{"id": 1, "access_token": False}], [{"id": 1}]],
    ids=["purged-request", "no-token", "token-not-returned"],
)
def test_existing_sign_link_is_none_when_request_is_gone(items):
    """A request that no longer resolves returns None so the caller drops the id."""
    client = FakeOdoo({("sign.request.item", "search_read"): items})

    assert odoo_sign_service.load_existing_sign_link(client, SIGN_REQUEST_ID) is None
