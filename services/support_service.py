import xmlrpc.client
import base64

from models.main import *
from config import Config


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


def create_ticket(user, from_url, filelist, category, description, title):
    db_user = db.session.query(User).filter(User.id == user.id).first()

    client = _get_client()

    ticket = {
        "name": f"[{category or 'Geral'}] {title or db_user.name}",
        "partner_name": db_user.name,
        "partner_email": db_user.email,
        "description": description,
        "x_studio_schema_1": db_user.schema,
        "x_studio_fromurl": from_url,
        "team_id": 1,
    }

    result = client(
        model="helpdesk.ticket",
        action="web_save",
        payload=[[], ticket],
        options={"specification": {}},
    )

    if filelist:
        for f in filelist:
            client(
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

    ticket = client(
        model="helpdesk.ticket",
        action="search_read",
        payload=[[["id", "=", result[0]["id"]]]],
        options={
            "fields": [
                "id",
                "access_token",
                "ticket_ref",
            ],
            "limit": 50,
        },
    )

    return ticket


def list_tickets(user):
    db_user = db.session.query(User).filter(User.id == user.id).first()

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
