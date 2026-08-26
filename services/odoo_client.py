"""ODOO XML-RPC client shared by the services that integrate with ODOO."""

import http.client
import socket
import xmlrpc.client

from config import Config
from utils import logger


class TimeoutTransport(xmlrpc.client.Transport):
    """ODOO integration transport class"""

    def __init__(self, timeout, *args, **kwargs):
        self.timeout = timeout
        super().__init__(*args, **kwargs)

    def make_connection(self, host):
        return http.client.HTTPConnection(host, timeout=self.timeout)


def get_client(context: str = "odoo client"):
    """Authenticate on the ODOO API and return an execute callable (None on timeout)."""
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
            "ODOO: Timeout connecting to ODOO API (%s)", context
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
                "ODOO: Timeout connecting to ODOO API (%s)", context
            )
            return None

    return execute
