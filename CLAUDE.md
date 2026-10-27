# NoHarm Backend - Agent Guide

## Overview

NoHarm is a healthcare/pharmacy clinical decision support system that helps prevent adverse drug events. This Flask-based backend provides APIs for prescription management, drug interaction checking, clinical interventions, patient monitoring, and regulatory compliance.

**Tech Stack:** Flask 3.1.3, SQLAlchemy 2.1.6, PostgreSQL, Redis, AWS (S3, SQS, Lambda)

## Architecture

### Application Structure

```
backend/
├── mobile.py                 # Application entrypoint
├── config.py                 # Configuration management
├── app/                      # Application factory and setup
│   ├── __init__.py          # Flask app factory (create_app)
│   ├── flask_config.py      # Environment-based configs
│   ├── extensions.py        # Flask extensions (db, jwt, cors, mail)
│   ├── blueprints.py        # Blueprint registration
│   ├── handlers.py          # Error handlers
│   ├── security.py          # Security headers
│   └── logging_config.py    # Logging configuration
├── models/                   # SQLAlchemy models (ORM)
│   ├── main.py              # Core models (User, Substance, etc.)
│   ├── prescription.py      # Prescription-related models
│   ├── regulation.py        # Regulatory models
│   ├── appendix.py          # Supporting/lookup models
│   ├── enums.py             # Enumerations
│   └── requests/            # Request validation models (Pydantic)
├── repository/               # Data access layer
├── services/                 # Business logic layer
│   ├── *_service.py         # Domain-specific services
│   ├── admin/               # Admin services
│   ├── regulation/          # Regulatory services
│   └── reports/             # Reporting services
├── routes/                   # API endpoint definitions (Flask blueprints)
│   ├── *_routes.py          # Route handlers
│   ├── admin/               # Admin routes
│   ├── regulation/          # Regulatory routes
│   └── reports/             # Report routes
├── decorators/               # Custom decorators
│   └── has_permission_decorator.py  # Permission checking
├── security/                 # Security utilities
├── utils/                    # Utility functions
├── exception/                # Custom exceptions
├── agents/                   # AI agent configurations
└── tests/                    # Test suite
```

### Design Patterns

**Layered Architecture:**
- **Routes Layer** (routes/): Handles HTTP requests/responses, parameter parsing, calls services
- **Services Layer** (services/): Contains business logic, orchestrates operations
- **Repository Layer** (repository/): Data access abstraction, database queries
- **Models Layer** (models/): SQLAlchemy ORM models, database schema

**Key Principles:**
- Application factory pattern for Flask app creation
- Repository pattern for data access
- Service layer for business logic separation
- Decorator-based authorization using `@has_permission`
- Schema-based multi-tenancy (each client has their own schema)

## Domain Concepts

### Core Entities

**Prescription Flow:**
- **Prescription**: Medical prescription with multiple drugs
- **PrescriptionDrug**: Individual drug in a prescription
- **Patient**: Patient information and history
- **Intervention**: Clinical pharmacist interventions on prescriptions
- **InterventionOutcome**: Results/outcomes of interventions

**Drug Information:**
- **Drug**: Drug catalog with attributes
- **Substance**: Active pharmaceutical ingredients
- **Outlier**: Statistical outliers for dose/frequency validation
- **DrugAttributes**: Schema-specific drug configurations

**Clinical Data:**
- **Exams**: Laboratory test results
- **ClinicalNotes**: Clinical observations and notes
- **Alerts**: Drug interaction, allergy, and protocol alerts

**Organizational:**
- **Segment**: Hospital units/departments
- **Department**: Department configuration
- **User**: System users (pharmacists, doctors, admins)
- **SchemaConfig**: Client-specific configurations

**Regulatory:**
- **RegSolicitation**: Regulatory approval requests
- **RegSolicitationDrug**: Drugs in regulatory requests

### Multi-Tenancy

NoHarm uses **PostgreSQL schema-based multi-tenancy**:
- Each client (hospital/organization) has a dedicated database schema
- Schema name is stored in JWT claims after authentication
- Schema is set per-request using SQLAlchemy execution options
- Public schema contains shared data (users, substances, global configs)

**Schema Switching:**
```python
db.session.connection(
    execution_options={"schema_translate_map": {None: schema_name}}
)
```

### Permission System

Role-based access control using decorators:
```python
@has_permission(Permission.READ_PRESCRIPTION, Permission.WRITE_PRESCRIPTION)
def some_service_function(user_permissions: list[Permission]):
    # Function receives user_permissions parameter
    # Can check permissions dynamically if needed
```

Permissions are defined in `decorators/has_permission_decorator.py`

## Database

### Primary Database
- **Type:** PostgreSQL
- **Connection:** every environment but test reads the credentials (`username`, `password`, `host`, `port`) from AWS Secrets Manager when the app is created (`create_app` → `database_config` in `app/flask_config.py`): secret `SECRET_ID_DB_API_USER` (default `prod/homolog/api_user`), database `DB_NAME` (default `postgres`). Development only (`ALLOW_CONNECTION_STRING`) may opt out by setting `POTGRESQL_CONNECTION_STRING`; production and staging ignore it. Tests use `TestConfig` and never call AWS. Don't read a secret in a config class body: it runs on import, tests included
- **SSL:** connections built from the secrets use `sslmode=verify-ca` with `sslrootcert` pointing to `config/certs.pem` (Amazon RDS root CAs, path resolved absolute as `DB_SSL_ROOT_CERT`). If the database moves to a CA not in the bundle, update the bundle first or every connection fails
- **ORM:** SQLAlchemy 2.1.6
- **Driver:** psycopg2. SQLAlchemy 2.1 maps a bare `postgresql://` URL to psycopg (version 3), so `app/flask_config.py` (`with_psycopg2`) pins the driver on every connection string. The connection strings in the environments need no driver. Don't switch to psycopg 3 without fixing what it rejects: model types that differ from the column (e.g. `presmed.slagrupamento` is `bigint`, declared `String(1)`), ids arriving as strings compared with `bigint` columns, and `IN :tuple` binds
- **Migrations:** Not currently using Alembic (manual schema management)

### Report Database
- **Bind Name:** `report`
- **Connection:** secret `SECRET_ID_DB_REPORT` (default `prod/replica/postgres-readonly`), database `REPORT_DB_NAME` (default `DB_NAME`); with the development opt-out, `REPORT_CONNECTION_STRING` (defaults to `POTGRESQL_CONNECTION_STRING`)
- **Purpose:** Separate database for reporting/analytics queries

### Redis
- **Purpose:** Session caching, rate limiting, temporary data
- **Configuration:** `Config.REDIS_HOST`, `Config.REDIS_PORT`
- **Connection:** SSL-enabled with 2s timeout

### Connection Pool
- Pool size: 20
- Max overflow: 30
- Pool recycle: 250s
- Pre-ping enabled for connection validation

## External Integrations

### AWS Services
- **S3:** File storage (NIFI_BUCKET_NAME, CACHE_BUCKET_NAME)
- **SQS:** Message queuing for async processing
- **CloudWatch:** Logging (NIFI_LOG_GROUP_NAME)
- **Lambda:** Serverless functions (SCORES_FUNCTION_NAME, BACKEND_FUNCTION_NAME)

### Third-Party APIs
- **Odoo:** ERP integration (ODOO_API_URL, ODOO_API_KEY)
- **OpenAI/Azure OpenAI:** AI-powered features (OPEN_AI_API_ENDPOINT)
- **Maritaca:** Brazilian LLM service (MARITACA_API_KEY)

### Deployment
- **Platform:** AWS Lambda (via Zappa)
- **Configuration:** zappa_settings.json
- **Environments:** Development, Production

## Common Patterns

### Adding a New API Endpoint

1. **Define Pydantic request model** in `models/requests/<domain>_request.py`:
```python
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

class MyDomainRequest(BaseModel):
    """Request model for my domain endpoint"""
    
    required_field: str
    required_int: int
    optional_field: Optional[str] = None
    optional_list: Optional[list[int]] = None
    date_field: Optional[datetime] = None
```

2. **Define route** in `routes/<domain>.py`:
```python
from flask import Blueprint, request
from decorators.api_endpoint_decorator import api_endpoint
from models.requests.my_domain_request import MyDomainRequest
from services import my_domain_service

app_domain = Blueprint("app_domain", __name__)

@app_domain.route("/domain/action", methods=["POST"])
@api_endpoint()  # Standard API wrapper
def create_action():
    """Create a new action"""
    return my_domain_service.create_action(
        request_data=MyDomainRequest(**request.get_json())
    )

@app_domain.route("/domain/list", methods=["GET"])
@api_endpoint()
def list_items():
    """List items with query parameters"""
    return my_domain_service.list_items(
        request_data=MyDomainRequest(**request.args.to_dict(flat=True))
    )

@app_domain.route("/domain/view/<int:id>", methods=["GET"])
@api_endpoint()
def view_item(id: int):
    """View single item by ID"""
    return my_domain_service.get_item(id=id)
```

3. **Implement service** in `services/<domain>_service.py`:
```python
from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.requests.my_domain_request import MyDomainRequest
from repository import my_domain_repository
from utils import status

@has_permission(Permission.REQUIRED_PERMISSION)
def create_action(request_data: MyDomainRequest, user_permissions: list[Permission]):
    """Create action with validated request data"""
    
    # Pydantic already validated the input
    # Access fields directly from request_data
    if not request_data.required_field:
        raise ValidationError(
            "Field is required",
            "errors.invalidParam",
            status.HTTP_400_BAD_REQUEST
        )
    
    # Call repository functions
    result = my_domain_repository.create(request_data)
    
    # Apply business logic
    # Return result
    return {"status": "success", "id": result.id}
```

4. **Create repository function** in `repository/<domain>_repository.py`:
```python
from models.main import db, MyModel
from models.requests.my_domain_request import MyDomainRequest

def create(request_data: MyDomainRequest):
    """Create new record from request data"""
    new_record = MyModel(
        field=request_data.required_field,
        value=request_data.required_int
    )
    
    db.session.add(new_record)
    db.session.flush()
    
    return new_record

def get_by_filters(request_data: MyDomainRequest):
    """Query with filters from request"""
    query = db.session.query(MyModel)
    
    if request_data.optional_field:
        query = query.filter(MyModel.field == request_data.optional_field)
    
    return query.all()
```

5. **Register blueprint** in `app/blueprints.py` (if new domain):
```python
from routes.my_domain import app_domain

def register_blueprints(app):
    # ... existing blueprints
    app.register_blueprint(app_domain)
```

**Key Points:**
- Always use Pydantic models for request validation
- For POST/PUT: use `request.get_json()` with `**` unpacking
- For GET: use `request.args.to_dict(flat=True)` with `**` unpacking
- Pydantic handles type conversion and validation automatically
- Service functions receive typed `request_data` parameter

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

### Date Handling

Use utilities in `utils/dateutils.py`:
- Timezone: America/Sao_Paulo (set in app/__init__.py)
- Always use timezone-aware datetime objects

### Logging

Logging is configured in `app/logging_config.py`:
- DynamoDB event logging for audit trails
- CloudWatch integration for production

## Configuration

### Environment Variables

Key configuration via environment variables (see `config.py`):

**Required:**
- `ENV`: development/production/test
- `SECRET_KEY`: JWT signing key
- `SECRET_ID_DB_API_USER` + `DB_NAME`: Main database credentials secret and name (`POTGRESQL_CONNECTION_STRING` replaces them in development only)
- `REDIS_HOST`, `REDIS_PORT`: Redis connection

**Optional but Important:**
- `ENCRYPTION_KEY`: For sensitive data encryption
- `API_KEY`: Internal API authentication
- `FEATURE_CONCILIATION_ALGORITHM`: Algorithm selection (default: FUZZY)

### Feature Flags

Check features using `services/feature_service.py`:
```python
if feature_service.is_feature_enabled(FeatureEnum.FEATURE_NAME, user):
    # Feature-specific logic
```

## Testing

### Test Structure
- **Location:** `tests/`
- **Framework:** pytest
- **Plugins:** pytest-flask, pytest-cov, pytest-order
- **Database:** PostgreSQL (required — SQLite not compatible due to schema-based multi-tenancy)

### Running Tests Locally

**IMPORTANT:** Always use `make` targets to run tests. Do NOT run `pytest` directly — the database must be running first and `ENV=test` must be set.

```bash
# First-time setup (starts Docker container + loads database from noharm-ai/database repo)
make test-setup

# Run all tests
make test

# Run a specific test file
make test-file FILE=tests/test_drug.py

# Run with coverage report
make test-cov

# Stop the database between work sessions (data preserved)
make db-stop
make db-start

# Full reset if something is broken
make db-reset
```

### Test Database
- Container defined in `docker-compose.test.yml` (PostgreSQL 16)
- Schema and seed data loaded from `github.com/noharm-ai/database` (same SQL files as CI)
- Connection string: `postgresql://postgres@localhost/noharm`
- Override via `TEST_DATABASE_URL` env var (see `TestConfig` in `app/flask_config.py`)
- Tests use the `demo` schema (set via `schema_translate_map` in `tests/conftest.py`)

### Test Isolation
- A session-scoped `clean_test_artifacts` fixture in `tests/conftest.py` deletes test-generated rows before and after each test session — tests are re-runnable without manual cleanup
- Test-generated prescriptions use IDs ≥ 100,000 (see `tests/utils/utils_test_prescription.py`)
- Seed substance IDs are < 10,000; test substances use IDs ≥ 10,000

### Test Ordering
Use `@pytest.mark.order(n)` for test execution order

### Test Data — Never Use Real People
**Never put a real person's data in code, tests, fixtures, comments, docstrings or commit messages.** This covers names, e-mail addresses, phone numbers, CPF, CNS, addresses, patient records and login credentials — and it explicitly includes the maintainers' and the user's own names. Do not reach for the name of whoever you are talking to, the git author, or anyone appearing in the repo as convenient sample data.

Always invent obviously fictitious data instead:

- **People:** `Fulano Beltrano`, `Ciclano de Tal`, `Maria Teste`
- **E-mail:** `fulano@example.com` (the `example.com` / `example.org` domains are reserved for exactly this)
- **Documents:** clearly invalid placeholders, never a real or checksum-valid CPF/CNS
- **Patients:** synthetic names and identifiers only — this is a healthcare product, so real patient data in a repository is a compliance problem, not just a style one

The rule holds even when the real value would be convenient or is already visible to you in the environment.

## Common Gotchas

1. **Schema Context Required:** Most queries need proper schema context set. Services usually handle this, but be aware in repository layer.

2. **Multi-Schema Queries:** When joining across schemas, be explicit about schema names.

3. **JWT Claims:** User context (schema, config) is stored in JWT claims, accessed via `get_jwt()`.

4. **Deferred Loading:** Some model fields use `deferred()` for performance. Explicitly load if needed.

5. **Connection Pool Exhaustion:** Long-running queries can exhaust pool. Use proper session management.

6. **Redis Timeouts:** Redis has 2s timeout. Don't use for operations requiring longer.

7. **Lambda Cold Starts:** First request after deployment may be slow (Lambda warming).

8. **Case Sensitivity:** PostgreSQL is case-sensitive with quoted identifiers.

9. **Timezones:** Always use America/Sao_Paulo timezone for date operations.

10. **Permission Decorators:** Service functions with `@has_permission` must accept `user_permissions` parameter.

## Key Business Logic

### Prescription Prioritization
- Algorithm in `services/prioritization_service.py`
- Scores prescriptions based on risk factors
- Used for pharmacist work queue

### Drug Interaction Checking
- Service: `services/alert_interaction_service.py`
- Checks drug-drug interactions
- Multiple severity levels

### Allergy Alert
- Rule: `alert_service.is_allergic`, used by the allergy alert and by the item's `allergy` flag in the drug list (`utils/drug_list.py`)
- The flag on `presmed.alergia` is set when the item arrives; the prescription view confirms it with the patient's `alergia` records (`repository/allergy_repository.py`): an active record of the item raises the alert, only inactive ones drop it, and with no record of the item the flag stands (some clients have no `alergia` records)
- A record is of the item when its `fkmedicamento` is the same drug (even if its `sctid` is stale), or by substance: `alergia.sctid` when present (filled by a separate job and trusted, since `fkmedicamento` does not always reference a `medicamento` record), otherwise the substance of its `fkmedicamento`. The cross reactivity check (`alert_interaction_service._get_allergies`) resolves the substance the same way
- The prescription view reads the records once (`_internal_get_prescription`) and passes them to the alerts and to the clinical notes, which list the active ones (source `pep`, one per name, cut at `_ALLERGY_RECORDS_LIMIT`: only information)
- Each drug list item carries why, for the maintainers (drug popover in the frontend): `allergyFlag` (`presmed.alergia` as it arrived) and `allergyRecord` (`active`/`inactive` from `alert_service.get_allergy_record_status`, `None` when no record of the item decided and the flag stood)
- Tests: `tests/unit/test_alerts_allergy.py` and `tests/integration/test_prescription_allergy.py`

### Prescalc Automatic Check
- Prescalc (`prescription_agg_service.create_agg_prescription_by_prescription`, non-CPOE) checks an individual prescription with nothing to validate, per schema feature: `AUTOMATIC_CHECK_DIET_ONLY` (only diets) and `AUTOMATIC_CHECK_WHITELIST_ONLY` (every drug, solution and procedure is `whiteList`); materials and diets may come along, any other item leaves it to the pharmacist
- The patient-day status is kept (a checked one is not made pending again); a new patient-day is checked when all its prescriptions are. When an item to validate arrives later, the regular flow unchecks both
- The check sets only status and audit (`extra.automaticCheck` names the feature): no `checkedindex`, no presmed marking
- CPOE has its own: `AUTOMATIC_CHECK_IF_NOT_VALIDATED_ITENS` checks the patient-day with no item to validate (`_automatic_check`)
- Tests: `tests/integration/test_prescalc_automatic_check.py`

### Outlier Detection
- Service: `services/outlier_service.py`
- Statistical analysis of dose/frequency
- Flags unusual prescriptions

### Clinical Decision Support
- Multiple alert types: interactions, allergies, protocols
- Integrated into prescription workflow
- Configurable per schema/segment

### Conciliation
- Service: `services/conciliation_service.py`
- Medication reconciliation between different prescriptions
- Configurable algorithm (FUZZY by default)

### Infection Control Rule
- Services: `services/infection_control/infection_control_status_service.py` (the rule) and `services/infection_control/antimicrobial_timeline_service.py` (how prescriptions are grouped into courses)
- Decides when an admission is followed, which pending reasons open or resolve, when evaluations close, and the PENDING / REVISED / CLOSED status
- **The rule lives only in this repository.** The review save, the manual follow, the backfill and the scheduled job all run it.
- Each run also stores on `ci_atendimento.indicadores` what it saw running (`admission_features`: each running course with its drug, substance, AWaRe level and start, and whether a non-conformity is in force). The worklist filters read it instead of joining prescriptions (`antimicrobials`: a list of criteria, each met by a running course of its own, so the drug or substance and the treatment day of a criterion go together and several can be asked at once, e.g. amoxicillin on D1 and vancomycin on D2; AWaRe is a separate filter), as the prescription prioritization reads `prescricao.indicadores`. Prescalc doesn't fill it: an admission it starts following shows up in those filters after the next job run.
- **The scheduled job is split between two repositories.** `backend-private` (`lambda_infection_control.py`) only schedules it: it lists the followed admissions of each schema with the feature on and calls `static.infection_control_sync` here synchronously, one admission at a time, so a single backend invocation (and database session) runs at once. The entry (`services/infection_control/infection_control_job_service.py`) applies the rule to that admission and answers `processed`, `changed` or `skipped` (a record held by a review save is skipped after a short lock timeout).
- Keep the contract (`schema`/`admission_number` in; `processed`/`changed`/`skipped` out) in step with `services/infection_control_service.py` in `backend-private`
- **Report summary.** Each run also keeps `ci_atendimento.resumo_acompanhamento` (`services/infection_control/infection_control_summary_service.py`): every antimicrobial course as the timeline groups it (a running one at day precision, `coveredUntil`), the department of each day and, refreshed by the job once a day and at close (DynamoDB), the culture facts. It is written only when it changes, since the job runs every hour, and the model column is `deferred()`. The infection control report (`reports/InfectionControlReport.py` in `long-running-tasks`) builds its files from it with SQL alone, so the course grouping never leaves this repository: change the summary's contract (`v`, documented in the service's docstring) together with that report. Closed admissions without a summary are filled by `POST /infection-control/backfill-summary`
- Tests: `tests/unit/test_infection_control_status_rule.py` and `tests/integration/infection_control/` (the job entry in `test_job.py`, the summary in `test_summary.py`)

### Drug Substance, Unit Conversion and Score Config (persisted by backend-private)
- Setting a drug's substance (`POST /drugs/substance`, `drug_service.update_substance`), saving its unit conversions (`POST /drugs/unit-conversion/<id>`, `unit_conversion_service.save_unit_conversion_for_drug`) and setting its division range before generating scores (`POST /outliers/generate/config/<segment>/<drug>/v2`, `drug_service.drug_config_to_generate_score`) only validate the request here and then call `backend-private` synchronously through `lambdautils.invoke_backend_function`: `lambda_substances.update_substance`, `lambda_unit_conversion.save_drug_conversions` and `lambda_scores.set_division_range`. The admin project calls the same commands.
- **Max dose is never calculated here.** `backend-private` recalculates it (and decides when a curator's value is kept) as part of those commands.
- **Don't re-implement the writes here** (copying substance attributes to every segment, `unidadeconverte` upserts, default measure unit, creating `medatributos` from the substance, divisor/weight, max dose recalculation): change them in `backend-private`, so backend and admin stay in step.
- Don't write in the request session before the call: backend-private commits in its own session, so a pending write here can block it. Read the result back with column queries (an ORM object already in the identity map keeps its old values).
- The unit conversion save and the score config send `process_scores: false`: the client generates the scores afterwards (`POST /drugs/process-scores/<id>`, or `prepare` + `single` in the generate-score drawer).
- Tests: `tests/integration/test_drug_attributes.py`, `tests/integration/test_unit_conversion_save.py` and `tests/integration/test_drug_score_config.py` stub the Lambda and assert the payload; the writes are tested in `backend-private`.

## Development Workflow

### Local Setup
```bash
python3 -m venv env
source env/bin/activate
pip3 install -r requirements.txt
python3 mobile.py
```

### Adding Dependencies
1. Add to `requirements.txt`
2. For production: also add to `requirements-prod.txt`
3. Run `pip install -r requirements.txt`

### Database Changes
1. Modify models in `models/`
2. No automated migrations (manual SQL required)
3. Test in development schema first
4. Coordinate with DBA for production

### Code Style
- Follow existing patterns (see above)
- Keep services focused on business logic
- Keep routes thin (just request/response handling)
- Use type hints where helpful
- Prefer explicit over implicit
- Add a brief docstring to every function you create

### Git Workflow
- Main branch: `master`
- Development branch: `develop`
- Feature branches off `develop`
- PR to `develop`, then merge to `master`

## Useful Commands

```bash
# Run development server
python3 mobile.py

# Run tests (requires Docker + database setup — see Testing section)
make test-setup   # first time only
make test
make test-file FILE=tests/test_drug.py
make test-cov

# Check code style
pylint services/
```

## AI/ML Features

### LLM Integration
- Services: `llm_service.py`, `agents/`
- Providers: OpenAI/Azure OpenAI, Maritaca
- Use cases: Clinical notes summarization, drug name normalization

## Security Considerations

1. **Authentication:** JWT-based with refresh tokens
2. **Authorization:** Permission-based access control
3. **SQL Injection:** Use SQLAlchemy ORM, parameterized queries
4. **XSS:** Escape HTML in routes (use `escape_html` from markupsafe)
5. **CSRF:** JWT cookie CSRF protection disabled (stateless API)
6. **Encryption:** Sensitive data encrypted with ENCRYPTION_KEY
7. **CORS:** Configured per environment in flask_config.py
8. **Security Headers:** Configured in app/security.py

## Monitoring & Logging

- **Application Logs:** CloudWatch (production)
- **Error Tracking:** Handler in app/handlers.py
- **Performance:** Lambda metrics in AWS Console

## Support & Resources

- **Repository:** https://github.com/noharm-ai/backend
- **Python Version:** 3.12+
- **Documentation:** This file + code comments
