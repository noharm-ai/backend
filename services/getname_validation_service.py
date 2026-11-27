"""Service: getname validation page (public, see docs/agents/getname-validation.md)

A schema's getname usually lives in the hospital's network, so only a browser
inside it can tell whether the names will show up. The admin project generates
a link (a row in public.schema_config_audit holding the hash of a secret); who
opens it runs the test in their own browser, with no login - the schema may not
have a single user yet. This service answers that page: what to test, the
getname token when the getname asks for one, and where the receipt goes (the
audit table and a support ticket).

Deliberately undecorated: there is no user to check a permission for. The token
in the link is the credential, and it never gives more than the three functions
below.
"""

import hashlib
import hmac
import ipaddress
from datetime import datetime, timezone
from urllib.parse import urlsplit

from markupsafe import escape

from exception.validation_error import ValidationError
from models.appendix import Memory, SchemaConfig, SchemaConfigAudit
from models.enums import MemoryEnum
from models.main import User, db
from models.requests.getname_validation_request import (
    GetnameValidationCheck,
    GetnameValidationResultRequest,
)
from repository import getname_validation_repository
from services import name_service, odoo_client
from utils import logger, status

# A tester retries while the network is being fixed, but the page is public:
# past this the link is spent and a new one has to be generated.
MAX_RUNS = 30
# Life of the getname token handed to the page: one lookup, made right away.
AUTH_TOKEN_SECONDS = 60
# What the app receives before the getname of a schema is configured (the
# default of auth_service is http://localhost/{idPatient}): localhost, no port.
_PLACEHOLDER_HOST = "localhost"
_ID_FLAG = "{idPatient}"
# ODOO ticket type "Validação" (support_service.TICKET_TYPE_LABELS)
_TICKET_TYPE = 5

_STATUS_LABELS = {
    "passed": "Passou",
    "failed": "Falhou",
    "not_applicable": "Não se aplica",
    "warning": "Atenção",
    "skipped": "Não executado",
}

_CHECK_LABELS = {
    "config": "Configuração do getname",
    "environment": "Navegador",
    "reachability": "Acesso ao getname",
    "health": "Serviço (health)",
    "database": "Banco de dados do hospital",
    "auth_config": "Autenticação configurada",
    "lookup": "Consulta de nome",
    # what the person saw when the page asked them to open the getname in a tab
    "manual": "O que apareceu ao abrir o getname em uma aba",
}

# The browser hides from the page why a connection failed and shows it in a
# tab: after a run that could not connect, the page asks what showed up there.
_OBSERVATION_LABELS = {
    "saw_getname_page": "A página do getname abriu",
    "saw_security_warning": "Aviso de segurança (certificado)",
    "saw_refused": "Conexão recusada",
    "saw_not_found": "Endereço não encontrado (DNS)",
    "saw_timeout": "Não respondeu",
}

_DIAGNOSIS_LABELS = {
    "ok": "Getname acessível e funcionando",
    "not_applicable": "Os nomes deste schema são resolvidos pelos servidores da NoHarm",
    "not_configured": "URL do getname não configurada",
    "mixed_content": "Getname em http: o navegador bloqueia a chamada a partir de uma página https",
    "local_network_denied": "O navegador não permite que a NoHarm acesse a rede local",
    "unreachable_timeout": "Sem resposta do getname: a rede deste computador não chega até ele",
    "unreachable": "Getname inacessível (DNS, conexão recusada ou certificado inválido)",
    "certificate": "O navegador não aceita o certificado https do getname",
    "certificate_accepted": "Funciona, mas só depois de aceitar o aviso de certificado no navegador",
    "connection_refused": "Conexão recusada: getname parado, em outra porta ou firewall rejeitando",
    "dns": "O computador não resolve o nome do servidor do getname (DNS)",
    "blocked_by_browser": "O getname abre em uma aba, mas o navegador bloqueia as chamadas da NoHarm",
    "cors": "Getname acessível, mas recusa chamadas da origem da NoHarm (CORS)",
    "http_error": "O getname respondeu com erro",
    "unhealthy_database": "O getname não consegue acessar o banco de dados do hospital",
    "auth_mismatch": "Tipo de autenticação da configuração diferente do getname instalado",
    "auth_secret_mismatch": "O getname recusou o token: o secret da configuração é diferente do instalado",
    "lookup_error": "A consulta de nome falhou no getname",
    "legacy_version": "Getname acessível, em uma versão antiga sem health check",
}


# What to ask the hospital's IT for, by diagnosis: (problem, request). The
# person running the test never contacts IT; the ticket carries the message for
# the NoHarm staff to send. {origin} is the site the browser calls from.
_IT_MESSAGES = {
    "local_network_denied": (
        "o navegador bloqueia o acesso de {origin} à rede local (Local Network Access).",
        "liberar {origin} na política LocalNetworkAccessAllowedForUrls do Chrome/Edge "
        "(LocalNetworkAllowedForUrls nas versões mais novas) nos computadores que usam a NoHarm.",
    ),
    "unreachable_timeout": (
        "o computador não recebe resposta do servidor do getname (tempo esgotado).",
        "liberar o acesso da rede dos computadores que usam a NoHarm ao servidor e à "
        "porta acima (firewall / roteamento).",
    ),
    "connection_refused": (
        "a conexão com o servidor do getname é recusada.",
        "confirmar que nenhum firewall rejeita conexões da rede dos computadores que "
        "usam a NoHarm para o servidor e a porta acima.",
    ),
    "dns": (
        "o nome do servidor do getname não é resolvido (DNS).",
        "fazer com que os computadores que usam a NoHarm resolvam o nome acima (DNS "
        "interno ou liberação do DNS externo).",
    ),
    "blocked_by_browser": (
        "o navegador bloqueia as chamadas de {origin} ao servidor do getname, embora o "
        "servidor abra normalmente em uma aba.",
        "verificar políticas do navegador, extensões ou antivírus que bloqueiem chamadas "
        "de {origin} a endereços da rede interna.",
    ),
    "unhealthy_database": (
        "o serviço de nomes da NoHarm (getname) não consegue conectar ao banco de dados "
        "do hospital.",
        "confirmar que o banco está no ar e que o usuário, a senha e a liberação de rede "
        "usados pelo getname continuam válidos.",
    ),
}


def _parse_token(token: str) -> tuple[int, str] | None:
    """Split a link token (``<id of the link row>-<secret>``)"""
    id_link, separator, secret = (token or "").partition("-")

    if not separator or not id_link.isdigit() or len(id_link) > 18 or not secret:
        return None

    return int(id_link), secret


def _expires_at(link: SchemaConfigAudit) -> datetime | None:
    """When a link stops working (None when the row has no valid date)"""
    try:
        expires_at = datetime.fromisoformat(str(link.extra.get("expires_at")))
    except ValueError:
        return None

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    return expires_at


def _resolve_link(
    token: str, lock: bool = False
) -> tuple[SchemaConfigAudit | None, str | None]:
    """The link a token opens, or why it opens none (``expired`` and
    ``exhausted`` are told apart only to who holds the right secret)."""
    parsed = _parse_token(token)
    if parsed is None:
        return None, None

    id_link, secret = parsed
    link = getname_validation_repository.get_link(id_link=id_link, lock=lock)
    if link is None:
        return None, None

    secret_hash = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(secret_hash, str(link.extra.get("token_hash", ""))):
        return None, None

    expires_at = _expires_at(link)
    if expires_at is None or expires_at <= datetime.now(tz=timezone.utc):
        return None, "expired"

    if getname_validation_repository.count_results(link) >= MAX_RUNS:
        return None, "exhausted"

    return link, None


def _require_link(token: str, lock: bool = False) -> SchemaConfigAudit:
    """The link of a token, or a 401 for the page to show as an invalid link"""
    link, _ = _resolve_link(token=token, lock=lock)

    if link is None:
        raise ValidationError(
            "Link de validação inválido ou expirado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    return link


def _base_url(name_url: str) -> str | None:
    """Root of the getname behind a name url, where /health answers. None when
    the url is not something a browser can call."""
    try:
        parts = urlsplit(name_url)
    except ValueError:
        return None

    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None

    try:
        port = parts.port
    except ValueError:
        return None

    if parts.hostname == _PLACEHOLDER_HOST and port is None:
        return None

    # the getname may sit behind a path prefix: keep what comes before its route
    prefix = parts.path.split("patient-name")[0] if "patient-name" in parts.path else "/"

    return f"{parts.scheme}://{parts.netloc}{prefix if prefix.endswith('/') else prefix + '/'}"


def _test_plan(schema: str) -> dict:
    """What the page has to test for a schema: the same getname settings the
    logged-in app receives at login (auth_service), minus the headers."""
    schema_config = (
        db.session.query(SchemaConfig).filter(SchemaConfig.schemaName == schema).first()
    )
    getname_config = (
        schema_config.config.get("getname", {})
        if schema_config and schema_config.config
        else {}
    ) or {}
    getname_type = getname_config.get("type") or "default"

    # the schema is only known after the link (a public table) was read, and a
    # session's schema is set before its first query: translate this one query
    memory = (
        db.session.query(Memory)
        .filter(Memory.kind == MemoryEnum.GETNAME.value)
        .execution_options(schema_translate_map={None: schema})
        .first()
    )
    name_memory = (memory.value if memory else None) or {}

    plan = {
        "getnameType": "proxy" if getname_type == "getname-proxy" else getname_type,
        "mode": "browser",
        "baseUrl": None,
        "nameUrl": None,
        "lookup": "skip",
    }

    # the names come through the NoHarm backend: nothing for a browser to reach
    if plan["getnameType"] == "proxy" or name_memory.get("proxy"):
        plan["mode"] = "backend"
        return plan

    name_url = name_memory.get("value") or ""
    base_url = _base_url(name_url)
    if base_url is None:
        plan["mode"] = "unconfigured"
        return plan

    plan["baseUrl"] = base_url
    plan["nameUrl"] = name_url if _ID_FLAG in name_url else None

    if plan["nameUrl"]:
        if plan["getnameType"] == "auth":
            plan["lookup"] = "token"
        elif not name_memory.get("headers"):
            # custom headers are a credential of an older setup: they are not
            # handed to an anonymous page, so that lookup is left out
            plan["lookup"] = "open"

    return plan


def get_validation(token: str) -> dict:
    """What a link tests. An unknown, malformed, expired or spent token answers
    valid=False with HTTP 200: on a public page a bad link is an expected case,
    and one shape of answer separates nothing for who is guessing."""
    link, reason = _resolve_link(token=token)

    if link is None:
        return {"valid": False, "reason": reason}

    runs = getname_validation_repository.count_results(link)

    return {
        "valid": True,
        "schema": link.schemaName,
        "expiresAt": _expires_at(link).isoformat(),
        "runs": runs,
        "maxRuns": MAX_RUNS,
        **_test_plan(schema=link.schemaName),
    }


def get_auth_token(token: str) -> dict:
    """The getname token for the lookup step, only for a schema whose getname
    asks for one. It is the token a logged-in user of the schema gets from
    GET /names/auth-token, with half the life."""
    link = _require_link(token=token)
    plan = _test_plan(schema=link.schemaName)

    if plan["lookup"] != "token":
        raise ValidationError(
            "Este getname não usa token",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    return {
        "token": name_service.generate_schema_token(
            schema=link.schemaName, seconds=AUTH_TOKEN_SECONDS
        )
    }


def _check_extra(check: GetnameValidationCheck) -> dict:
    """A check as stored in the result row"""
    return {
        "id": check.id,
        "status": check.status,
        "code": check.code,
        "http_status": check.httpStatus,
        "duration_ms": check.durationMs,
        "detail": check.detail,
    }


def _client_ip(value: str | None) -> str | None:
    """The address a run was posted from, when it is one. It is the public
    address the request left the hospital with (its internet link, usually a
    NAT): the computer's address inside the hospital never reaches a server."""
    try:
        return str(ipaddress.ip_address((value or "").strip()))
    except ValueError:
        return None


def _it_message_html(plan: dict, extra: dict, client_ip: str | None) -> str:
    """The message the NoHarm staff can send to the hospital's IT, when the
    diagnosis is something IT has to act on; empty otherwise. The person who
    ran the test is not asked to contact anyone."""
    message = _IT_MESSAGES.get(extra["diagnosis"])
    if message is None or not plan["baseUrl"]:
        return ""

    server = urlsplit(plan["baseUrl"])
    port = server.port or (443 if server.scheme == "https" else 80)
    origin = extra["environment"].get("pageOrigin") or "o site da NoHarm"
    problem, request = (text.format(origin=origin) for text in message)

    lines = [
        "Olá! Estamos validando o acesso ao serviço de nomes da NoHarm (getname) e o "
        "teste feito em um computador do hospital falhou.",
        "",
        f"Problema: {problem}",
        f"Servidor do getname: {server.hostname}, porta {port} ({server.scheme})",
        f"Site que faz as chamadas: {origin}",
        f"O que precisamos: {request}",
    ]
    browser = " em ".join(
        value
        for value in (
            extra["environment"].get("browser"),
            extra["environment"].get("platform"),
        )
        if value
    )
    if browser or client_ip:
        lines.append("")
    if browser:
        lines.append(f"Navegador usado no teste: {browser}.")
    if client_ip:
        lines += [
            f"O teste saiu para a internet pelo IP público {client_ip} (o endereço "
            "interno do computador não é visível para a NoHarm).",
        ]

    return (
        "<h4>Mensagem sugerida para a TI do hospital</h4>"
        "<p>Quem executou o teste não foi orientado a procurar a TI: o contato é "
        "nosso.</p>"
        f"<blockquote>{'<br/>'.join(str(escape(line)) for line in lines)}</blockquote>"
    )


def _receipt_html(
    schema: str, plan: dict, extra: dict, run: int, client_ip: str | None = None
) -> str:
    """The receipt of a run, for the ticket. Every value typed by the page is
    escaped: the page is public and this is rendered by the helpdesk."""
    environment = extra["environment"]
    diagnosis = extra["diagnosis"]
    permissions = ", ".join(
        f"{name}: {state}" for name, state in (environment.get("permissions") or {}).items()
    )

    summary = [
        ("Schema", schema),
        ("Resultado", _STATUS_LABELS.get(extra["status"], extra["status"])),
        ("Diagnóstico", _DIAGNOSIS_LABELS.get(diagnosis, diagnosis or "-")),
        ("Execução", f"{run} de {MAX_RUNS} (link {extra['link_id']})"),
        ("Tipo do getname", plan["getnameType"]),
        ("URL testada", plan["baseUrl"] or "-"),
        ("Versão do getname", environment.get("getnameVersion") or "-"),
        ("Origem da página", environment.get("pageOrigin") or "-"),
        ("IP público de quem testou", client_ip or "-"),
        ("Navegador", environment.get("browser") or "-"),
        ("Sistema operacional", environment.get("platform") or "-"),
        ("User agent", environment.get("userAgent") or "-"),
        ("Endereço do getname", environment.get("targetAddressSpace") or "-"),
        ("Permissões de rede local", permissions or "-"),
    ]

    rows = "".join(
        f"<tr><td><strong>{escape(label)}</strong></td><td>{escape(value)}</td></tr>"
        for label, value in summary
    )
    checks = "".join(
        "<tr>"
        f"<td>{escape(_CHECK_LABELS.get(check['id'], check['id']))}</td>"
        f"<td>{escape(_STATUS_LABELS.get(check['status'], check['status']))}</td>"
        f"<td>{escape(_OBSERVATION_LABELS.get(check['code'], check['code']) or '-')}</td>"
        f"<td>{escape(check['http_status'] if check['http_status'] is not None else '-')}</td>"
        f"<td>{escape(check['duration_ms'] if check['duration_ms'] is not None else '-')}</td>"
        f"<td>{escape(check['detail'] or '')}</td>"
        "</tr>"
        for check in extra["checks"]
    )

    return (
        "<h4>Validação do getname</h4>"
        "<p>Teste executado no navegador de quem abriu o link de validação, sem "
        "login. Os dados abaixo foram informados pela página.</p>"
        f"<table>{rows}</table>"
        "<h4>Etapas</h4>"
        "<table><tr><th>Etapa</th><th>Resultado</th><th>Código</th>"
        "<th>HTTP</th><th>ms</th><th>Detalhe</th></tr>"
        f"{checks}</table>"
        f"{_it_message_html(plan=plan, extra=extra, client_ip=client_ip)}"
    )


def _ticket_title(schema: str, result_status: str) -> str:
    """Title of the ticket of a link; follows the latest run"""
    return f"[Validação] Getname {schema}: {_STATUS_LABELS.get(result_status, result_status)}"


def _open_ticket(client, link: SchemaConfigAudit, title: str, receipt: str) -> dict:
    """Open the ticket of a link, requested by who generated it"""
    ticket = {
        "name": title,
        "description": receipt,
        "x_studio_schema_1": link.schemaName,
        "x_studio_tipo_chamado": _TICKET_TYPE,
        "team_id": 1,
    }

    creator = db.session.query(User).filter(User.id == link.createdBy).first()
    if creator is not None:
        partner = client(
            model="res.partner",
            action="search_read",
            payload=[[["email", "=", creator.email]]],
            options={"fields": ["id"]},
        )
        if partner and partner[0].get("id") is not None:
            ticket["partner_id"] = partner[0]["id"]
        else:
            ticket["partner_name"] = creator.name
            ticket["partner_email"] = creator.email

    created = client(
        model="helpdesk.ticket",
        action="web_save",
        payload=[[], ticket],
        options={"specification": {}},
    )
    if not created:
        return {}

    id_ticket = created[0]["id"]
    saved = client(
        model="helpdesk.ticket",
        action="search_read",
        payload=[[["id", "=", id_ticket]]],
        options={"fields": ["id", "ticket_ref"], "limit": 1},
    )

    return {
        "ticket_id": id_ticket,
        "ticket_ref": str(saved[0].get("ticket_ref") or id_ticket) if saved else str(id_ticket),
    }


def _update_ticket(client, ticket: dict, title: str, receipt: str) -> None:
    """A new run of a link that already has a ticket: the receipt goes in as a
    note and the title follows the latest result"""
    client(
        model="mail.message",
        action="create",
        payload=[
            {
                "message_type": "comment",
                "body": receipt,
                "model": "helpdesk.ticket",
                "res_id": ticket["ticket_id"],
                "subtype_id": 2,
            }
        ],
        options={},
    )
    client(
        model="helpdesk.ticket",
        action="write",
        payload=[[ticket["ticket_id"]], {"name": title}],
        options={},
    )


def _register_ticket(
    link: SchemaConfigAudit, previous: list[SchemaConfigAudit], title: str, receipt: str
) -> dict:
    """One ticket per link: the first run opens it, the others add a note. The
    helpdesk failing never loses the run - it is saved without a ticket and the
    next run tries to open one again."""
    ticket = next(
        (
            {
                "ticket_id": result.extra["ticket_id"],
                "ticket_ref": result.extra.get("ticket_ref"),
            }
            for result in previous
            if (result.extra or {}).get("ticket_id")
        ),
        None,
    )

    try:
        client = odoo_client.get_client(context="getname validation")
        if client is None:
            return ticket or {}

        if ticket is None:
            return _open_ticket(client=client, link=link, title=title, receipt=receipt)

        _update_ticket(client=client, ticket=ticket, title=title, receipt=receipt)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.backend_logger.warning(
            "getname validation: ticket not registered for schema %s",
            link.schemaName,
            exc_info=True,
        )

    return ticket or {}


def save_result(
    token: str,
    request_data: GetnameValidationResultRequest,
    client_ip: str | None = None,
) -> dict:
    """Save the receipt of a run and put it on the ticket of the link.

    ``client_ip`` (the address the run was posted from) goes to the ticket
    only, for who talks to the hospital's IT: it is not kept in the result row,
    which the admin project lists."""
    # the lock makes two runs of one link queue here, so a link never opens two
    # tickets and never goes past MAX_RUNS
    link = _require_link(token=token, lock=True)
    previous = getname_validation_repository.list_results(link)
    plan = _test_plan(schema=link.schemaName)

    checks = [_check_extra(check) for check in request_data.checks]
    # the verdict is recomputed: a run with a failed step never counts as passed
    result_status = (
        "failed"
        if any(check["status"] == "failed" for check in checks)
        else request_data.status
    )

    extra = {
        "link_id": link.id,
        "status": result_status,
        "diagnosis": request_data.diagnosis,
        "getname_type": plan["getnameType"],
        "base_url": plan["baseUrl"],
        "checks": checks,
        "environment": request_data.environment.model_dump(),
        "ticket_id": None,
        "ticket_ref": None,
    }

    ticket = _register_ticket(
        link=link,
        previous=previous,
        title=_ticket_title(schema=link.schemaName, result_status=result_status),
        receipt=_receipt_html(
            schema=link.schemaName,
            plan=plan,
            extra=extra,
            run=len(previous) + 1,
            client_ip=_client_ip(client_ip),
        ),
    )
    extra["ticket_id"] = ticket.get("ticket_id")
    extra["ticket_ref"] = ticket.get("ticket_ref")

    getname_validation_repository.add_result(link=link, extra=extra)

    return {
        "saved": True,
        "status": result_status,
        "ticket": extra["ticket_ref"],
        "runs": len(previous) + 1,
        "maxRuns": MAX_RUNS,
    }
