# NoHarm Backend - Agent Guide

## Overview

NoHarm is a healthcare/pharmacy clinical decision support system that helps prevent adverse drug events. This Flask-based backend provides APIs for prescription management, drug interaction checking, clinical interventions, patient monitoring, and regulatory compliance.

**Tech Stack:** Flask 3.1.3, SQLAlchemy 2.1.8, PostgreSQL, Redis, AWS (S3, SQS, Lambda, DynamoDB), deployed to AWS Lambda via Zappa (`zappa_settings.json`). Python 3.12+.

This file holds what applies to every change. The rules of each domain live in their own docs, listed under [Domain Rules](#domain-rules): **read the doc of an area before changing it**. A longer architecture overview for humans is in `docs/architecture.md`.

## Architecture

Layered, one folder per layer:

- `routes/` — Flask blueprints: parse the request into a Pydantic model, call a service. Keep them thin. Registered in `app/blueprints.py`
- `services/` — business logic, permission checks (`@has_permission`)
- `repository/` — data access (SQLAlchemy queries)
- `models/` — ORM models (`main.py`, `prescription.py`, `regulation.py`, `appendix.py`, `enums.py`); request models in `models/requests/`
- Also: `app/` (factory `create_app`, configs in `flask_config.py`, extensions, error handlers, security headers, logging), `decorators/`, `security/`, `utils/`, `exception/`, `agents/` (LLM), `tests/`. Entrypoint `mobile.py`, settings `config.py`

### Multi-Tenancy

PostgreSQL **schema-based multi-tenancy**: each client (hospital) has its own schema; the `public` schema holds shared data (users, substances, global configs). The schema name comes from the JWT claims (`get_jwt()`) and is set per request:
```python
db.session.connection(
    execution_options={"schema_translate_map": {None: schema_name}}
)
```
Most queries need this context; be explicit about schema names when joining across schemas.

### Permission System

```python
@has_permission(Permission.READ_PRESCRIPTION, Permission.WRITE_PRESCRIPTION)
def some_service_function(user_permissions: list[Permission]):
    # user_permissions is injected only when the function declares it
```
The `Permission` enum is in `security/permission.py`, the permissions of each role in `security/role.py`. Every service function a route calls needs `@has_permission`: `@api_endpoint` answers 401 when no permission check ran.

### Feature Flags

```python
if feature_service.has_feature(FeatureEnum.FEATURE_NAME):
    ...
```

## Database

- **Primary:** every environment but test reads the credentials (`username`, `password`, `host`, `port`) from AWS Secrets Manager when the app is created (`create_app` → `database_config` in `app/flask_config.py`): secret `SECRET_ID_DB_API_USER` (default `prod/homolog/api_user`), database `DB_NAME` (default `postgres`). Development only (`ALLOW_CONNECTION_STRING`) may opt out by setting `POTGRESQL_CONNECTION_STRING`; production and staging ignore it. Tests use `TestConfig` and never call AWS. Don't read a secret in a config class body: it runs on import, tests included
- **SSL:** connections built from the secrets use `sslmode=verify-ca` with `sslrootcert` pointing to `config/certs.pem` (Amazon RDS root CAs, path resolved absolute as `DB_SSL_ROOT_CERT`). If the database moves to a CA not in the bundle, update the bundle first or every connection fails
- **Driver:** psycopg2. SQLAlchemy 2.1 maps a bare `postgresql://` URL to psycopg (version 3), so `app/flask_config.py` (`with_psycopg2`) pins the driver on every connection string. The connection strings in the environments need no driver. Don't switch to psycopg 3 without fixing what it rejects: model types that differ from the column (e.g. `presmed.slagrupamento` is `bigint`, declared `String(1)`), ids arriving as strings compared with `bigint` columns, and `IN :tuple` binds
- **Report database** (bind `report`, for reporting/analytics queries): secret `SECRET_ID_DB_REPORT` (default `prod/replica/postgres-readonly`), database `REPORT_DB_NAME` (default `DB_NAME`); with the development opt-out, `REPORT_CONNECTION_STRING` (defaults to `POTGRESQL_CONNECTION_STRING`)
- **Pool:** size 20, max overflow 30, recycle 250s, pre-ping. Long-running queries can exhaust it
- **Redis** (`Config.REDIS_HOST`, `Config.REDIS_PORT`): caching, rate limiting, temporary data. SSL, **2s timeout**: don't use it for longer operations
- **No migrations tool** (no Alembic): change the models in `models/`, write the SQL by hand, test in a development schema first, coordinate with the DBA for production

## Configuration

Environment variables in `config.py`. Required: `ENV` (development/production/test), `SECRET_KEY` (JWT), `SECRET_ID_DB_API_USER` + `DB_NAME` (`POTGRESQL_CONNECTION_STRING` replaces them in development only), `REDIS_HOST`, `REDIS_PORT`. Also: `ENCRYPTION_KEY` (sensitive data), `API_KEY` (internal API auth), `FEATURE_CONCILIATION_ALGORITHM` (default FUZZY). External services (S3, SQS, Lambda `SCORES_FUNCTION_NAME`/`BACKEND_FUNCTION_NAME`, Odoo, OpenAI/Azure OpenAI, Maritaca) are configured there too.

## Common Patterns

### Adding a New API Endpoint

Route → service → repository, with a Pydantic request model. A small complete example: `routes/tag.py` → `tag_service.list_tags` → `tag_repository.list_tags`, with `TagListRequest` in `models/requests/tag_request.py`.

1. **Request model** in `models/requests/<domain>_request.py` (a `pydantic.BaseModel`; optional fields default to `None`)
2. **Route** in `routes/<domain>.py`, wrapped by `@api_endpoint()` (`decorators/api_endpoint_decorator.py`):
```python
@app_domain.route("/domain/action", methods=["POST"])
@api_endpoint()
def create_action():
    """Create a new action"""
    return my_domain_service.create_action(
        request_data=MyDomainRequest(**request.get_json())
    )
```
   For POST/PUT use `request.get_json()`; for GET `request.args.to_dict(flat=True)`. Path params as `<int:id>`
3. **Service** in `services/<domain>_service.py`: `@has_permission(...)`, receives the typed `request_data` (and `user_permissions` if it declares it), applies the business rules, calls the repository
4. **Repository** in `repository/<domain>_repository.py`: queries with `db.session`; `db.session.add` + `flush` to get ids
5. **Register** a new blueprint in `app/blueprints.py`

### Error Handling

Raise `ValidationError` for business logic errors:
```python
from exception.validation_error import ValidationError
from utils import status

raise ValidationError(
    "User-friendly message",
    "i18n.translation.key",
    status.HTTP_400_BAD_REQUEST
)
```

### Dates and Logging

- Timezone America/Sao_Paulo (set in `app/__init__.py`); always timezone-aware datetimes; helpers in `utils/dateutils.py`
- Logging in `app/logging_config.py` (DynamoDB audit events, CloudWatch in production)

## Testing

**Always use the `make` targets. Do NOT run `pytest` directly** — the database must be running first and `ENV=test` must be set.

```bash
make test-setup   # first time: starts the Docker container + loads the database from noharm-ai/database
make test
make test-file FILE=tests/test_drug.py
make test-cov
make db-stop      # between work sessions (data preserved); make db-start to resume
make db-reset     # full reset if something is broken
```

- pytest with pytest-flask, pytest-cov, pytest-order (`@pytest.mark.order(n)` for execution order)
- **PostgreSQL only** (container in `docker-compose.test.yml`, PostgreSQL 16; SQLite is not compatible with the schema-based multi-tenancy). Schema and seed data from `github.com/noharm-ai/database` (same SQL files as CI). Connection string `postgresql://postgres@localhost/noharm`, override with `TEST_DATABASE_URL` (`TestConfig` in `app/flask_config.py`)
- Tests use the `demo` schema (set via `schema_translate_map` in `tests/conftest.py`)
- A session-scoped `clean_test_artifacts` fixture in `tests/conftest.py` deletes test-generated rows before and after each test session — tests are re-runnable without manual cleanup
- Test-generated prescriptions use IDs ≥ 100,000 (see `tests/utils/utils_test_prescription.py`); seed substance IDs are < 10,000, test substances use IDs ≥ 10,000
- Tests never call AWS: an autouse fixture in `tests/conftest.py` makes the noharm-store return no item, and nothing else is stubbed for you. A test of a service that calls a Lambda patches it itself (e.g. `utils.lambdautils.aws.get_client` in `tests/integration/test_drug_attributes.py`)

### Test Data — Never Use Real People
**Never put a real person's data in code, tests, fixtures, comments, docstrings or commit messages.** This covers names, e-mail addresses, phone numbers, CPF, CNS, addresses, patient records and login credentials — and it explicitly includes the maintainers' and the user's own names. Do not reach for the name of whoever you are talking to, the git author, or anyone appearing in the repo as convenient sample data.

Always invent obviously fictitious data instead:

- **People:** `Fulano Beltrano`, `Ciclano de Tal`, `Maria Teste`
- **E-mail:** `fulano@example.com` (the `example.com` / `example.org` domains are reserved for exactly this)
- **Documents:** clearly invalid placeholders, never a real or checksum-valid CPF/CNS
- **Patients:** synthetic names and identifiers only — this is a healthcare product, so real patient data in a repository is a compliance problem, not just a style one

The rule holds even when the real value would be convenient or is already visible to you in the environment.

## Domain Rules

Each area below has rules that are easy to break from a distance. **Before changing code in an area, read its doc.** The ⚠ lines are contracts with another repository: a change there ships together with that repository.

- **Prescription view** (`GET /prescriptions/<id>`, `prescription_view_service`), **drug interactions** (`alert_interaction_service`) and **allergy alert** (`alert_service.is_allergic`, `allergy_repository`) → [`docs/agents/prescription-view.md`](docs/agents/prescription-view.md). The most used endpoint, and prescalc runs the same pipeline: don't add a query to it (what was read once is passed along; `tests/integration/test_prescription_view_queries.py` guards it), and never query or search a list per item or per pair of items
- **Schema params** (`schema_params_service`, `store_repository`, `models/schema_params.py`, `models/alert_config.py`: alert types and interaction rules per schema, in the DynamoDB `noharm-store`) → [`docs/agents/schema-params.md`](docs/agents/schema-params.md). ⚠ Written and validated by **admin**, only read here: change a section together with admin; the defaults must keep today's behaviour
- **Infection control** → [`services/infection_control/CLAUDE.md`](services/infection_control/CLAUDE.md). It loads by itself only for files under `services/infection_control/`: read it before changing `routes/infection_control/`, `repository/infection_control/` (the `gatilhos` contract lives there too), `models/infection_control*.py` or `tests/integration/infection_control/`. ⚠ The scheduled job contract and the exams cache queue are shared with **backend-private**; the report summary (`resumo_acompanhamento`) with **long-running-tasks**; the enums with the frontend
- **Admission queues** (`admission_queue_service`, `fila_atendimento`) → [`docs/agents/admission-queues.md`](docs/agents/admission-queues.md). ⚠ backend-private writes the infection control queue and runs the consumers' jobs
- **Prescalc automatic check** (`prescription_agg_service`, features `AUTOMATIC_CHECK_*`) → [`docs/agents/prescalc-automatic-check.md`](docs/agents/prescalc-automatic-check.md)
- **Prescription test cases** (`POST /prescriptions/test-case`, maintainers, test schema only) → [`docs/agents/prescription-test-cases.md`](docs/agents/prescription-test-cases.md). Never name a schema in the code
- **Drug substance, unit conversion and score config** → [`docs/agents/drug-config.md`](docs/agents/drug-config.md). ⚠ Persisted by **backend-private** (called through Lambda): only validate here, don't re-implement its writes, and never calculate max dose here

Smaller areas, no doc of their own: prescription prioritization (`prioritization_service.py`, scores prescriptions for the pharmacist work queue), outlier detection (`outlier_service.py`, dose/frequency statistics), conciliation (`conciliation_service.py`, algorithm set by `FEATURE_CONCILIATION_ALGORITHM`), LLM features (`llm_service.py`, `agents/`: clinical notes summarization, drug name normalization).

When you add or change a domain rule, document it in that area's doc (or a new one in `docs/agents/`, indexed here), not in this file.

## Common Gotchas

1. **Schema context required:** most queries need the schema set (services usually handle it); be aware in the repository layer
2. **Deferred loading:** some model fields use `deferred()` for performance; load them explicitly when needed
3. **Case sensitivity:** PostgreSQL is case-sensitive with quoted identifiers
4. **Lambda cold starts:** the first request after a deploy may be slow

## Security

- Use the SQLAlchemy ORM or bound parameters, never SQL built from strings
- Escape HTML in routes (`escape_html` from markupsafe)
- Sensitive data is encrypted with `ENCRYPTION_KEY`
- Auth is JWT with refresh tokens (cookie CSRF protection disabled: stateless API); CORS per environment in `app/flask_config.py`; security headers in `app/security.py`

## Development Workflow

- **Local setup:** `python3 -m venv env && source env/bin/activate && pip3 install -r requirements.txt && python3 mobile.py`
- **Dependencies:** add to `requirements.txt`, and to `requirements-prod.txt` for production
- **Code style:** follow the existing patterns; services hold the business logic, routes stay thin; type hints where helpful; prefer explicit over implicit; **add a brief docstring to every function you create**. Lint with `pylint services/`
- **Git:** main branch `master`, development branch `develop`; feature branches off `develop`, PR to `develop`, then merge to `master`
