import xmlrpc.client
import base64

from models.main import *
from config import Config


def create_ticket(user, from_url, attachment):
    db_user = db.session.query(User).filter(User.id == user.id).first()

    apiUrl = Config.ODOO_API_URL
    apiDB = Config.ODOO_API_DB
    apiUser = Config.ODOO_API_USER
    apiKey = Config.ODOO_API_KEY

    common = xmlrpc.client.ServerProxy(apiUrl + "common")
    uid = common.authenticate(apiDB, apiUser, apiKey, {})
    models = xmlrpc.client.ServerProxy(apiUrl + "object")

    ticket = {
        "name": f"[Dúvida] {db_user.name}",
        "partner_name": db_user.name,
        "partner_email": db_user.email,
        "description": "teste description",
        "x_studio_schema_1": db_user.schema,
        "x_studio_fromurl": from_url,
        "team_id": 1,
    }

    # print("ticket", ticket)

    # with open("image.png", "rb") as image_file:
    #     image = image_file.read()
    #     # print("image", image)
    #     imageBase64 = base64.b64encode(image)

    # result = models.execute_kw(
    #     apiDB,
    #     uid,
    #     apiKey,
    #     "helpdesk.ticket",
    #     "web_save",
    #     [[], ticket],
    #     {"specification": {}},
    # )

    # print(image)

    if attachment:
        models.execute_kw(
            apiDB,
            uid,
            apiKey,
            "ir.attachment",
            "create",
            [
                {
                    "name": "Anexo",
                    "res_model": "helpdesk.ticket",
                    "res_id": 217,
                    "type": "binary",
                    "datas": str(base64.b64encode(attachment.read()))[2:],
                }
            ],
        )
