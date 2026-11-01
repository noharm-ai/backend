"""Repository: drug name -> sctid mapping (DynamoDB noharm_cultura_medicamento_sctid)

The table is shared by every schema: backend-private resolves the drug names of
cultures and of allergies (alergia) through it, and admin corrects it. It is
keyed by the normalized name only, so an entry applies to all schemas.
"""

import unicodedata
from datetime import datetime, timezone
from decimal import Decimal

from utils import aws

_TABLE = "noharm_cultura_medicamento_sctid"
# backend-private keeps an entry whose origin is manual
_ORIGIN_MANUAL = "manual"


def normalize_name(name: str) -> str:
    """The key of a drug name: upper case, no accents, single spaces.

    Same as backend-private cultura_cache_service.normalize_key_part, so both
    sides build the same key"""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(char for char in text if not unicodedata.combining(char))

    return " ".join(text.upper().split())


def put_sctid(name: str, sctid: int | None, idclass: str | None):
    """Map the drug name to the substance, creating the entry when the name has
    none, as a manual entry the backend-private job does not overwrite.

    Without sctid the entry stays, with no substance: removing it would make
    backend-private infer a substance for the name again"""
    table = aws.get_resource("dynamodb", region_name="sa-east-1").Table(_TABLE)

    # same attributes as backend-private cultura_cache_service.build_sctid_entry
    table.put_item(
        Item={
            "nome": normalize_name(name),
            "nome_original": name.strip(),
            "sctid": Decimal(sctid) if sctid is not None else None,
            "idclasse": idclass,
            "origem": _ORIGIN_MANUAL,
            "probabilidade": None,
            "atualizado_em": datetime.now(timezone.utc).isoformat(),
        }
    )
