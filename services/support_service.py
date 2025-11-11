"""Service: support related operations"""

import xmlrpc.client
import base64
import http.client
import socket


from models.main import db, User
from models.appendix import GlobalMemory
from models.enums import GlobalMemoryEnum
from config import Config
from decorators.has_permission_decorator import has_permission, Permission
from agents import n0_agent
from exception.validation_error import ValidationError
from utils import status, logger
from services import vector_search_service
from repository import user_repository
from security.role import Role


class TimeoutTransport(xmlrpc.client.Transport):
    """ODOO integration transport class"""

    def __init__(self, timeout, *args, **kwargs):
        self.timeout = timeout
        super().__init__(*args, **kwargs)

    def make_connection(self, host):
        return http.client.HTTPConnection(host, timeout=self.timeout)


def _get_client():
    transport = TimeoutTransport(timeout=15)

    common = xmlrpc.client.ServerProxy(
        Config.ODOO_API_URL + "common", transport=transport
    )
    try:
        uid = common.authenticate(
            Config.ODOO_API_DB, Config.ODOO_API_USER, Config.ODOO_API_KEY, {}
        )
    except socket.timeout:
        logger.backend_logger.warning(
            "ODOO: Timeout connecting to ODOO API (support service)"
        )

        return None

    models = xmlrpc.client.ServerProxy(
        Config.ODOO_API_URL + "object", transport=transport
    )

    def execute(model, action, payload, options):
        try:
            return models.execute_kw(
                Config.ODOO_API_DB,
                uid,
                Config.ODOO_API_KEY,
                model,
                action,
                payload,
                options,
            )
        except socket.timeout:
            logger.backend_logger.warning(
                "ODOO: Timeout connecting to ODOO API (support service)"
            )
            return None

    return execute


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


@has_permission(Permission.WRITE_SUPPORT)
def create_ticket(
    user_context: User,
    from_url,
    filelist,
    category,
    description,
    title,
    nzero_response: str,
    nzero_summary: str,
):
    """Creates a new ticket"""

    db_user = db.session.query(User).filter(User.id == user_context.id).first()

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

    ticket = {
        "name": f"[{category or 'Geral'}] {title or db_user.name}",
        "description": description,
        "x_studio_schema_1": user_context.schema,
        "x_studio_fromurl": from_url,
        "x_studio_tipo_de_chamado": category,
        "team_id": 1,
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
                        "datas": str(base64.b64encode(f.read()))[2:],
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
                        "datas": str(base64.b64encode(f.read()))[2:],
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

    return id_ticket


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

        my_tickets_ids = [t.get("id") for t in my_tickets]
        following = []
        for f in following_all:
            if f.get("id") not in my_tickets_ids:
                following.append(f)

        if (
            Permission.WRITE_USERS in user_permissions
            and partner[0]
            and partner[0].get("parent_id", None)
        ):
            organization = client(
                model="helpdesk.ticket",
                action="search_read",
                payload=[
                    [
                        [
                            "commercial_partner_id",
                            "in",
                            [partner[0].get("parent_id", [])[0]],
                        ],
                    ]
                ],
                options=options,
            )
    else:
        my_tickets = client(
            model="helpdesk.ticket",
            action="search_read",
            payload=[[["partner_email", "=", db_user.email]]],
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

    return pending_tickets


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
