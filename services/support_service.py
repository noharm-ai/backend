"""Service: support related operations"""

import base64

from agents import n0_agent
from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import GlobalMemory
from models.enums import GlobalMemoryEnum
from models.main import User, UserExtra, db
from models.requests.knowledge_base_request import (
    KnowledgeBaseListRequest,
)
from repository import knowledge_base_repository, user_repository
from security.role import Role
from services import odoo_client, training_service, vector_search_service
from utils import status


def _get_client():
    """Authenticate on the ODOO API and return an execute callable (None on timeout)."""
    return odoo_client.get_client(context="support service")


# ODOO ticket type ids, as sent by the "Tipo de chamado" select. ODOO resolves the
# id itself; these labels only title the ticket.
TICKET_TYPE_LABELS = {
    1: "Solicitação",
    2: "Erro",
    4: "Dúvida",
    5: "Validação",
    6: "Integração fora do ar",
    9: "Sugestão",
}


def _ticket_type_fields(category):
    """Map the ``category`` form field onto the right ODOO field, plus its label.

    Older frontends send the type as a label string (``"Erro"``) bound to
    ``x_studio_tipo_de_chamado``; current ones send the ODOO id (``2``, as a
    string — the request is multipart) bound to ``x_studio_tipo_chamado``. None of
    the legacy labels parse as an int, so ``int()`` tells the two apart with no
    ambiguity for any value either version can send.

    The legacy branch has to stay reachable: ``SupportFormAI`` still sends labels,
    and a user's browser may hold a stale bundle.
    """
    try:
        type_id = int(category)
    except (TypeError, ValueError):
        return {"x_studio_tipo_de_chamado": category}, category

    return {"x_studio_tipo_chamado": type_id}, TICKET_TYPE_LABELS.get(type_id)


@has_permission(Permission.READ_SUPPORT)
def ask_n0(question: str, user_context: User = None):
    """Ask a question to the n0 agent and return the response"""
    if not question:
        raise ValidationError(
            "Pergunta inválida",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    user = db.session.query(User).filter(User.id == user_context.id).first()

    response = n0_agent.run_n0(query=question, user=user)

    return {"agent": str(response)}


@has_permission(Permission.READ_SUPPORT)
def get_related_kb(question: str):
    """Get related articles from open kb"""
    if not question:
        raise ValidationError(
            "Pergunta inválida",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    config_memory = (
        db.session.query(GlobalMemory)
        .filter(GlobalMemory.kind == GlobalMemoryEnum.USER_KB.value)
        .first()
    )

    search_config = vector_search_service.SearchConfig(**config_memory.value)
    search_config.max_results = 3

    vectors = vector_search_service.search(query=question, config=search_config)

    articles = {}
    for v in vectors:
        metadata = v.get("metadata", {})
        if "article_id" in metadata:
            articles[metadata.get("article_id")] = metadata.get("article_name")

    results = []
    for art_id, art_name in articles.items():
        results.append({"id": art_id, "name": art_name})

    return results


@has_permission(Permission.READ_SUPPORT)
def ask_n0_form(question: str):
    """Ask a question to the n0 form agent and return the response"""
    if not question:
        raise ValidationError(
            "Pergunta inválida",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    response = n0_agent.run_n0_form(query=question)

    return {"agent": response}


def _check_mandatory_training(
    user_context: User, user_permissions: list[Permission], urgent: bool
) -> bool:
    """Users who still owe mandatory training may not open tickets. Holders of
    ADMIN_SUPPORT can override it for an urgent ticket. Returns whether the
    override was used, so the ticket can record it"""
    # Never block someone who cannot comply: the training endpoints all require
    # READ_BASIC_FEATURES, which SUPPORT_REQUESTER and SUPPORT_MANAGER do not
    # hold, so gating them would be a permanent lockout with no way out. If those
    # roles ever gain the permission, the gate starts applying on its own.
    if Permission.READ_BASIC_FEATURES not in user_permissions:
        return False

    if not training_service.has_pending_mandatory_training(
        user_id=user_context.id, schema=user_context.schema
    ):
        return False

    if urgent and Permission.ADMIN_SUPPORT in user_permissions:
        return True

    raise ValidationError(
        "Você precisa concluir os treinamentos obrigatórios antes de abrir um chamado.",
        "errors.pendingMandatoryTraining",
        status.HTTP_400_BAD_REQUEST,
    )


@has_permission(Permission.WRITE_SUPPORT)
def create_ticket(
    user_context: User,
    user_permissions: list[Permission],
    from_url,
    filelist,
    category,
    description,
    title,
    nzero_response: str,
    nzero_summary: str,
    urgent: bool = False,
):
    """Creates a new ticket"""

    training_override = _check_mandatory_training(
        user_context=user_context, user_permissions=user_permissions, urgent=urgent
    )

    db_user = db.session.query(User).filter(User.id == user_context.id).first()

    if training_override:
        # the support team needs to see why this one skipped the training gate
        description = (
            f"{description or ''}"
            "<hr/><h4>Chamado urgente</h4>"
            "Aberto com treinamento obrigatório pendente "
            f"(bypass ADMIN_SUPPORT — {db_user.email})"
        )

    client = _get_client()

    if client is None:
        raise ValidationError(
            "Não foi possível conectar ao serviço de suporte.",
            "errors.connectionTimeout",
            status.HTTP_504_GATEWAY_TIMEOUT,
        )

    partner = client(
        model="res.partner",
        action="search_read",
        payload=[[["email", "=", db_user.email]]],
        options={"fields": ["id", "name", "parent_id"]},
    )

    type_fields, type_label = _ticket_type_fields(category)

    ticket = {
        "name": f"[{type_label or 'Geral'}] {title or db_user.name}",
        "description": description,
        "x_studio_schema_1": user_context.schema,
        "x_studio_fromurl": from_url,
        "team_id": 1,
        **type_fields,
    }

    if partner and partner[0].get("id", None) is not None:
        ticket["partner_id"] = partner[0].get("id")
    else:
        ticket["partner_name"] = db_user.name
        ticket["partner_email"] = db_user.email

    result = client(
        model="helpdesk.ticket",
        action="web_save",
        payload=[[], ticket],
        options={"specification": {}},
    )

    if result is None:
        raise ValidationError(
            "Não foi possível conectar ao serviço de suporte.",
            "errors.connectionTimeout",
            status.HTTP_504_GATEWAY_TIMEOUT,
        )

    attachments = []

    if filelist:
        for f in filelist:
            att = client(
                model="ir.attachment",
                action="create",
                payload=[
                    {
                        "name": f.filename,
                        "res_model": "helpdesk.ticket",
                        "res_id": result[0]["id"],
                        "type": "binary",
                        "raw": base64.b64encode(f.read()).decode("ascii"),
                    }
                ],
                options={},
            )

            attachments.append(att)

    ticket = client(
        model="helpdesk.ticket",
        action="search_read",
        payload=[[["id", "=", result[0]["id"]]]],
        options={
            "fields": [
                "id",
                "access_token",
                "ticket_ref",
                "partner_id",
            ],
            "limit": 50,
        },
    )

    if len(ticket) > 0 and ticket[0].get("partner_id", None) != None:
        # add message
        client(
            model="mail.message",
            action="create",
            payload=[
                {
                    "message_type": "email",
                    "author_id": ticket[0]["partner_id"][0],
                    "body": description,
                    "model": "helpdesk.ticket",
                    "res_id": result[0]["id"],
                    "subtype_id": 1,
                    "attachment_ids": attachments,
                }
            ],
            options={},
        )

    if nzero_response:
        # add nzero response message
        client(
            model="mail.message",
            action="create",
            payload=[
                {
                    "message_type": "comment",
                    "body": nzero_response,
                    "model": "helpdesk.ticket",
                    "res_id": result[0]["id"],
                    "subtype_id": 2,
                }
            ],
            options={},
        )

    if nzero_summary:
        # add nzero question summary
        client(
            model="mail.message",
            action="create",
            payload=[
                {
                    "message_type": "comment",
                    "body": nzero_summary,
                    "model": "helpdesk.ticket",
                    "res_id": result[0]["id"],
                    "subtype_id": 2,
                }
            ],
            options={},
        )

    return ticket


@has_permission(Permission.WRITE_SUPPORT)
def add_attachment(id_ticket: int, files):
    """Add attachment to ticket"""

    if not id_ticket:
        raise ValidationError(
            "ID ticket inválido",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if not files:
        raise ValidationError(
            "Nenhum arquivo selecionado",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    client = _get_client()

    if client is None:
        raise ValidationError(
            "Não foi possível conectar ao serviço de suporte para enviar o anexo.",
            "errors.connectionTimeout",
            status.HTTP_504_GATEWAY_TIMEOUT,
        )

    ticket = client(
        model="helpdesk.ticket",
        action="search_read",
        payload=[[["id", "=", id_ticket]]],
        options={
            "fields": [
                "id",
                "access_token",
                "ticket_ref",
                "partner_id",
            ],
            "limit": 1,
        },
    )

    for key in files:
        attachments = []

        for f in files.getlist(key):
            att = client(
                model="ir.attachment",
                action="create",
                payload=[
                    {
                        "name": f.filename,
                        "res_model": "helpdesk.ticket",
                        "res_id": int(id_ticket),
                        "type": "binary",
                        "raw": base64.b64encode(f.read()).decode("ascii"),
                    }
                ],
                options={},
            )

            attachments.append(att)

        client(
            model="mail.message",
            action="create",
            payload=[
                {
                    "message_type": "email",
                    "author_id": ticket[0]["partner_id"][0],
                    "body": f"Anexo: {key.replace('[]', '')}",
                    "model": "helpdesk.ticket",
                    "res_id": int(id_ticket),
                    "subtype_id": 1,
                    "attachment_ids": attachments,
                }
            ],
            options={},
        )

    return int(id_ticket)


@has_permission(Permission.READ_SUPPORT)
def list_tickets_v2(user_context: User, user_permissions: list[Permission]):
    """List user tickets, following and organization tickets (when allowed)"""

    db_user = db.session.query(User).filter(User.id == user_context.id).first()

    client = _get_client()

    if client is None:
        # fail silently, return empty lists
        return {
            "myTickets": [],
            "following": [],
            "organization": [],
        }

    partner = client(
        model="res.partner",
        action="search_read",
        payload=[[["email", "=", db_user.email]]],
        options={"fields": ["id", "name", "parent_id"]},
    )

    options = {
        "fields": [
            "name",
            "partner_name",
            "access_token",
            "message_needaction",
            "message_needaction_counter",
            "has_message",
            "create_date",
            "stage_id",
            "date_last_stage_update",
            "description",
            "ticket_ref",
            "x_studio_tipo_de_chamado",
            "tag_ids",
        ],
        "limit": 50,
        "order": "create_date desc",
    }

    my_tickets = []
    following = []
    organization = []

    if partner:
        partner_ids = [item.get("id") for item in partner]

        my_tickets = client(
            model="helpdesk.ticket",
            action="search_read",
            payload=[
                [
                    ["partner_id", "in", partner_ids],
                ]
            ],
            options=options,
        )

        following_all = client(
            model="helpdesk.ticket",
            action="search_read",
            payload=[
                [
                    ["message_partner_ids", "in", partner_ids],
                ]
            ],
            options=options,
        )

        # ODOO answers False, not [], when a search matches nothing
        my_tickets = my_tickets if my_tickets else []
        following_all = following_all if following_all else []

        my_tickets_ids = [t.get("id") for t in my_tickets]
        following = []
        for f in following_all:
            if f.get("id") not in my_tickets_ids:
                following.append(f)

    else:
        my_tickets = client(
            model="helpdesk.ticket",
            action="search_read",
            payload=[[["partner_email", "=", db_user.email]]],
            options=options,
        )

    if Permission.ADMIN_SUPPORT in user_permissions:
        organization_schemas = [db_user.schema]
        extra = (
            db.session.query(UserExtra).filter(UserExtra.idUser == db_user.id).first()
        )
        if extra:
            extra_schemas = extra.config.get("schemas", [])

            for schema in extra_schemas:
                schema_name = schema.get("name", None)
                if schema_name:
                    organization_schemas.append(schema_name)

        ignored_tags = [46, 48, 58, 60]

        organization = client(
            model="helpdesk.ticket",
            action="search_read",
            payload=[
                [
                    [
                        "x_studio_schema_1",
                        "in",
                        organization_schemas,
                    ],
                    ["tag_ids", "not in", ignored_tags],
                ]
            ],
            options=options,
        )

    return {
        "myTickets": my_tickets if my_tickets else [],
        "following": following if following else [],
        "organization": organization if organization else [],
    }


@has_permission(Permission.READ_SUPPORT)
def list_pending_action(user_context: User):
    """List user tickets with pending actions"""

    db_user = db.session.query(User).filter(User.id == user_context.id).first()

    client = _get_client()

    if client is None:
        # fail silently, return empty list
        return []

    partner = client(
        model="res.partner",
        action="search_read",
        payload=[[["email", "=", db_user.email]]],
        options={"fields": ["id", "name", "parent_id"]},
    )

    options = {
        "fields": [
            "name",
            "partner_name",
            "access_token",
        ],
        "limit": 50,
        "order": "create_date desc",
    }

    pending_tickets = []

    if partner:
        partner_ids = [item.get("id") for item in partner]

        stage_waiting_response = 3
        tag_no_response = 23

        pending_tickets = client(
            model="helpdesk.ticket",
            action="search_read",
            payload=[
                [
                    ["partner_id", "in", partner_ids],
                    ["stage_id", "in", [stage_waiting_response]],
                    ["tag_ids", "in", [tag_no_response]],
                ]
            ],
            options=options,
        )

    # ODOO answers False, not [], when a search matches nothing
    return pending_tickets if pending_tickets else []


@has_permission(Permission.WRITE_SUPPORT)
def create_closed_ticket(user_context: User, description):
    """Creates a closed ticket (answered by AI)"""

    if not description:
        raise ValidationError(
            "Descricao de chamado inválida",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    client = _get_client()

    if client is None:
        raise ValidationError(
            "Não foi possível conectar ao serviço de suporte.",
            "errors.connectionTimeout",
            status.HTTP_504_GATEWAY_TIMEOUT,
        )

    ticket = {
        "name": "Chamado encerrado pelo NZero",
        "description": description,
        "x_studio_schema_1": user_context.schema,
        "x_studio_tipo_de_chamado": "Dúvida",
        "team_id": 1,
        "stage_id": 4,
    }

    result = client(
        model="helpdesk.ticket",
        action="web_save",
        payload=[[], ticket],
        options={"specification": {}},
    )

    if result:
        return result[0]["id"]

    return None


@has_permission(Permission.READ_SUPPORT)
def list_requesters(user_context: User):
    """List users that can create tickets"""
    users = user_repository.get_users_by_role(
        schema=user_context.schema, role=[Role.SUPPORT_REQUESTER, Role.SUPPORT_MANAGER]
    )

    results = []
    for user in users:
        results.append({"name": user.name, "email": user.email})

    return {"requesters": results}


@has_permission(Permission.READ_BASIC_FEATURES)
def list_knowledge_base_articles(request_data: KnowledgeBaseListRequest):
    results = knowledge_base_repository.list_knowledge_base(request_data=request_data)

    return [
        {
            "link": kb.link,
            "title": kb.title,
            "description": kb.description,
        }
        for kb in results
    ]
