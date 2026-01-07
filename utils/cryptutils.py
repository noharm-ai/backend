"""Utils: Cryptography utilities"""

import base64
from typing import Union

from cryptography.fernet import Fernet

from config import Config
from utils import logger


def encrypt_data(plaintext: str) -> Union[str, None]:
    """Encrypt data using Fernet (symmetric encryption)."""
    if not plaintext:
        return None

    try:
        fernet = Fernet(Config.ENCRYPTION_KEY.encode())
        encrypted = fernet.encrypt(plaintext.encode("utf-8"))
        return base64.b64encode(encrypted).decode("utf-8")
    except Exception as e:
        logger.backend_logger.error(f"Encryption error: {e}")
        raise ValueError("Erro ao criptografar dados sensíveis")
