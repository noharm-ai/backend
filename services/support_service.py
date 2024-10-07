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
    db_user = db.session.query(User).filter(User.id == user_context.id).first()

    client = _get_client()

    ticket = {
        "name": f"[{category or 'Geral'}] {title or db_user.name}",
        "partner_name": db_user.name,
        "partner_email": db_user.email,
        "description": description,
        "x_studio_schema_1": db_user.schema,
        "x_studio_fromurl": from_url,
        "x_studio_tipo_de_chamado": category,
        "team_id": 1,
    }

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
def list_tickets(user_context: User):
    db_user = db.session.query(User).filter(User.id == user_context.id).first()

    client = _get_client()

    tickets = client(
        model="helpdesk.ticket",
        action="search_read",
        payload=[[["partner_email", "=", db_user.email]]],
        options={
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
            ],
            "limit": 50,
        },
    )

    return tickets
