"""Service: support related operations"""

import xmlrpc.client
import base64

from models.main import db, User
from config import Config
from decorators.has_permission_decorator import has_permission, Permission


def _get_client():
    common = xmlrpc.client.ServerProxy(Config.ODOO_API_URL + "common")
    uid = common.authenticate(
        Config.ODOO_API_DB, Config.ODOO_API_USER, Config.ODOO_API_KEY, {}
    )
    models = xmlrpc.client.ServerProxy(Config.ODOO_API_URL + "object")

    def execute(model, action, payload, options):
        return models.execute_kw(
            Config.ODOO_API_DB,
            uid,
            Config.ODOO_API_KEY,
            model,
            action,
            payload,
            options,
        )

    return execute


@has_permission(Permission.WRITE_SUPPORT)
def create_ticket(user_context: User, from_url, filelist, category, description, title):
    """Creates a new ticket"""

    db_user = db.session.query(User).filter(User.id == user_context.id).first()

    client = _get_client()

    partner = client(
        model="res.partner",
        action="search_read",
        payload=[[["email", "=", db_user.email]]],
        options={"fields": ["id", "name", "parent_id"]},
    )

    ticket = {
        "name": f"[{category or 'Geral'}] {title or db_user.name}",
        "description": description,
        "x_studio_schema_1": db_user.schema,
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

    return ticket


@has_permission(Permission.READ_SUPPORT)
def list_tickets_v2(user_context: User, user_permissions: list[Permission]):
    """List user tickets, following and organization tickets (when allowed)"""

    db_user = db.session.query(User).filter(User.id == user_context.id).first()

    client = _get_client()

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
        "myTickets": my_tickets,
        "following": following,
        "organization": organization,
    }
