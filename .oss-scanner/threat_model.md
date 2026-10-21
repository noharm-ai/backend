# Threat model

## What this project does and where untrusted input enters
- NoHarm backend: the Flask API behind a clinical decision support product used by hospital pharmacists to
  review prescriptions and prevent adverse drug events. It stores patient, prescription, exam and clinical
  note data, so a vulnerability can affect both patient privacy and patient safety.
- Multi-tenant: each client (hospital) has its own PostgreSQL schema. The tenant comes from the JWT claims of
  the authenticated user, and `dbSession.setSchema` points the request's connection at it. Shared data
  (users, substances, global configuration) lives in the `public` schema.
- Untrusted input:
  - Every HTTP route in `routes/` (JSON bodies, query strings, path parameters). Routes are wrapped by
    `decorators/api_endpoint_decorator.py` (JWT check, schema selection) and services by
    `decorators/has_permission_decorator.py` (role/permission check; a request that never checks a
    permission is rejected).
  - Authentication and token flows in `routes/authentication.py` and `services/auth_service.py`
    (login, refresh tokens, schema switching, password reset, OAuth/OIDC providers).
  - Free text written by users (interventions, clinical notes, memory, knowledge base, tags) that is later
    rendered by the web client, put into reports or sent to an LLM.
  - Data imported from hospital systems (prescriptions, exams, notes) — treat it as untrusted too.
- Trusted callers: `static.py` entry points (`prescalc`, `atendcalc`, `infection_control_sync`, ...) are
  invoked as AWS Lambda functions by our own infrastructure, not over HTTP. The HTTP routes in
  `routes/static.py` (`/static/<schema>/...`) are different: they take the schema from the URL and are not
  wrapped by `api_endpoint`, so they are in scope.

## Components that matter most / least
- Most important: cross-tenant access (reading or writing another schema's data), authentication and
  session handling, the permission model (`security/permission.py`, `security/role.py`, `has_permission`),
  SQL injection (raw `text()` queries in `repository/` and `services/reports/`), sensitive data exposure
  (patient data, other users' data, secrets in responses or logs), and admin routes reachable outside their
  intended environment (`api_endpoint(is_admin=True)`).
- Also in scope: SSRF or path traversal through file, report or S3 operations; prompt injection that makes an
  LLM feature leak another tenant's or patient's data; unsafe deserialization.
- Lower priority: denial of service, missing hardening headers with no demonstrated impact.
- Out of scope: `tests/`, `scripts/`, `docs/`, deployment configuration (`zappa_settings.json`,
  `.github/`), and issues that require a compromised host, database or AWS account. Writes delegated to
  `backend-private` (drug substance, unit conversion, score config — see CLAUDE.md) are implemented in
  that repository, not here.

## How to exercise it
- The image has PostgreSQL with the `noharm` database already loaded from `noharm-ai/database`
  (schema plus synthetic seed data; tenant schema `demo`, login `demo` / `demo`). The image's entrypoint
  starts it when the container starts; if the entrypoint was bypassed, start it with
  `.oss-scanner/start-db.sh` before running the app or the integration tests.
- Tests: `python -m pytest tests/unit` (no database) and `python -m pytest tests/integration`
  (needs the database). `ENV=test` is already set in the image. `tests/conftest.py` shows how to log in
  and get a JWT (`get_access`) and how roles are assigned for a test user.
- Run the API with `python mobile.py` (listens on `127.0.0.1:5000`), or use `app.test_client()` from
  `mobile.py` as the tests do.
- There is no Redis, AWS or LLM provider in the image; code paths that need them fail or are stubbed in
  the tests.

## How you rate severity
- Critical: unauthenticated access to patient data, authentication bypass, cross-tenant read or write, or
  SQL injection reachable by any authenticated user.
- High: privilege escalation between roles within a tenant, authenticated access to data the user's
  permissions do not cover, stored XSS that runs in other users' sessions, secrets exposed in responses.
- Medium: issues that need an unusual role or configuration, information leaks without patient data, or
  reflected XSS.
- Low: denial of service and hardening gaps without a demonstrated impact.

## Anything to leave alone
- The default `SECRET_KEY`, mail settings and connection strings in `config.py` are development defaults;
  production sets them through the environment. Report them only if a production code path still uses a
  default.
- All names, e-mails and documents in the seed data and tests are fictitious; do not report them as leaked
  personal data.
- Reports and patches: include the route, the role the attacker needs, and a test under `tests/` that
  reproduces the issue where possible.
