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

### Schema Params in the noharm-store (written by admin, only read here)
- Settings of a schema that clients can change, one section per feature, in the DynamoDB `noharm-store` (`Config.NOHARM_STORE_TABLE`): `pk = schema_params`, `sk = <schema>`, the sections in `data`. **The admin project writes and validates it; this project only reads it** (`repository/store_repository.py`, `services/schema_params_service.py`, root model `models/schema_params.py`, one model per section). Change a section together with admin
- There is no global item: whatever the schema's item does not set comes from the code defaults (the model defaults), which keep the behaviour the system has without any config. Each section is validated on its own: an invalid one falls back to its defaults and the others still apply. When the table can't be read (1s timeouts, no retry) the defaults apply, so a failure never changes behaviour. Loaded with the other configs of the prescription view (`_get_configs` → `config_data["schema_params"]`), once per request (one read for every section). Named params, not config, because `public.schema_config` is a different thing (the client's infra/integration settings)
- New section: a model whose defaults keep today's behaviour, a field in `SchemaParams`, and the same section in admin
- Maintainers see them, read only, through `GET /schema-params` (`routes/schema_params.py`, `schema_params_service.view_schema_params`, `Permission.MAINTAINER`), from the prescription screen's alerts card: `params` (in force, defaults filled in), `custom` (only what the schema's item sets), `status` (`found`, `not_found`, `read_error`) and `invalidSections`. The frontend modal (`src/features/prescription/SchemaParams/SchemaParams.tsx`) shows "não se aplica" where a setting has no effect (rx's `ignoreFrequencies` and `requireIntervalIntersection`, protocol's `level`): change it there too if those rules change. Tests: `tests/integration/test_schema_params_view.py`
- Tests never call AWS: an autouse fixture in `tests/conftest.py` makes the store return no item. Tests: `tests/unit/test_schema_params.py` and `tests/unit/test_store_repository.py`

#### Section `alerts`
- `types`: one entry per `alert_service` alert type (`DrugAlertTypeEnum` value, e.g. `kidney`, `allergy`, `maxDose`; `AlertTypesConfig` has a field for each, kept in step by a test). Any type can be turned off (`enabled: false`): `find_alerts` neither lists nor counts it. A type's `level` (`low`/`medium`/`high`) replaces the level its alerts set (all of them, e.g. pregnant D and X), and so the prescription level (`alertStats.level`) and the prioritization; unset or unknown keeps the alert's own. Not applied to `protocol`, whose level each protocol sets. Admin shows each type's default level as a copy (`ALERT_TYPES.defaultLevel`): changing an alert's level in `alert_service` means changing it there too. The culture class alert never stands in for a `cultureResistant` turned off. The item's `allergy` flag in the drug list is patient information and stays when the allergy alert is off
- `types.kidney` also chooses the renal function exams (`tpexam`, in order, matched in lower case) compared with the drug's kidney limit: `adultExams` (over 17, default `ckd21`, `ckd`: the first with a value decides) and `pediatricExams` (up to 17, default `swrtz2`, `swrtz1`: the first below the limit raises). An empty list keeps the defaults; an exam the schema chose is named in the text by its initials and unit. Dialysis raises the alert whatever the exams. The IRA alert (vancomycin) reads its renal function the same way, from `adultExams` (the first with a value), whatever the patient's age, as it did with `ckd21`/`ckd`
- `interactions`, per relation kind (`it`, `dt`, `dm`, `iy`, `sl`, `rx`): `enabled` (off: the kind is neither shown nor counted), `ignoreLevels` (alerts of these levels are neither shown nor counted: the final level, after the dm SN and iy shared time adjustments, checked after `build_alert` by `evaluate_level_rule`), `ignoreFrequencies` (either item's `presmed.frequenciadia` in the list, e.g. SN 33 / ACM 44; not for `rx`) and `requireIntervalIntersection` (shown only when the items share an administration time; not for `rx`). Applied as rules in `alert_interaction_service.evaluate_kind_rules` (`config_kind_disabled`, `config_ignored_frequency`, `config_interval_intersection`, plus `config_ignored_level` on the built alert; only when configured), so the prescription view and the interaction trace (which also returns `alertConfig`) agree
- Model: `models/alert_config.py`. Read by `_get_alerts` from `config_data["schema_params"].alerts` (the trace gets the same from `get_interaction_evaluation_context`), so the view and prescalc (`alertStats` → prioritization) agree; prescriptions already processed keep their counts until prescalc runs again
- Tests: `tests/unit/test_alert_config.py`, `tests/integration/test_interaction_trace.py` and `tests/integration/test_prescription_allergy.py`

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

### Prescalc Performance
- Prescalc (`static.prescalc` and `static.atendcalc` → `prescription_agg_service`) is the most executed flow of the application, and almost all of its time is the prescription view (`prescription_view_service.static_get_prescription`). Each statement is a round trip to the database: before adding a read, look for one the run already does
- **The admission's data is read once.** The non-CPOE entry builds the view twice in a row, of the prescription and of its prescription-day. It passes the same `admission_data` dict to both, and the second view reuses what the first read and does not depend on the items: configs, interventions, allergy records, allergies by substance, clinical notes stats, exams and cultures. `_admission_scope` empties the dict for another admission, patient, segment or conciliation. A new read of the view that doesn't depend on the items goes through `_once`; what the items change (drug list, alerts, protocols, headers) is read by both. The shared data is only read: don't change it in place
- The view's first query (`_get_prescription_data`) loads the deferred columns `_format` always reads (`undefer`: `Prescription.notes`, `Patient.observation`, `Patient.alert`), `is_cpoe` comes from the segment it joins, and the features it reads with the other memories are kept for the request (`feature_service.set_features`), so `feature_service.has_feature` and `memory_service.has_feature_nouser` don't read them again
- The hooks at the end (`follow_from_prescalc`, `admission_queue_service.notify`) check their feature before opening a savepoint: a schema without it pays no statement for an antimicrobial
- `db_utils.set_schema` checks a schema once per process (only existing ones are remembered) and `prescalc_repository.acquire_admission_lock` tries the lock without waiting before the wait with `lock_timeout`
- `alert_interaction_service.find_relations` compares every pair of items: keep what runs per pair cheap (the pairs are kept unique in a dict, pairs without any relation are skipped at once). It also runs on every load of the prescription screen
- Tests: `tests/integration/test_prescalc_admission_data.py` (the reads, the view with shared data against the view alone, and `STATEMENT_BUDGET`, the statements a run may take) and `tests/unit/test_prescalc_repository.py` (the lock)

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
- Each drug evaluated in a review tells why it is given (`ci_avaliacao_atm.tp_tratamento`, `AntimicrobialTreatmentTypeEnum`: empirical, culture guided, surgical or medical prophylaxis) and the infection foci (`tp_focos_infeccao`, an array of `InfectionFocusEnum`: one or more), required by the review save; only a prophylaxis may leave the foci empty. Evaluations made before they were asked have both empty. The frontend keeps the same codes (`models/InfectionControlEnum.ts`) and their labels
- **The rule lives only in this repository.** The review save, the manual follow, the backfill and the scheduled job all run it.
- Each run also stores on `ci_atendimento.indicadores` what it saw running (`admission_features`: each running course with its drug, substance, AWaRe level and start, plus `evaluatedPosology` when its evaluation watches posology changes and no posology reason of the drug is open, and whether a non-conformity is in force). The worklist filters read it instead of joining prescriptions (`antimicrobials`: a list of criteria, each met by a running course of its own, so the drug or substance and the treatment day of a criterion go together and several can be asked at once, e.g. amoxicillin on D1 and vancomycin on D2; AWaRe is a separate filter), as the prescription prioritization reads `prescricao.indicadores`. Prescalc doesn't fill it: an admission it starts following shows up in those filters after the next job run.
- **The scheduled job is split between two repositories.** `backend-private` (`lambda_infection_control.py`) only schedules it: it lists the followed admissions of each schema with the feature on and calls `static.infection_control_sync` here synchronously, one admission at a time, so a single backend invocation (and database session) runs at once. The entry (`services/infection_control/infection_control_job_service.py`) applies the rule to that admission and answers `processed`, `changed` or `skipped` (a record held by a review save is skipped after a short lock timeout).
- Keep the contract (`schema`/`admission_number` in; `processed`/`changed`/`skipped` out) in step with `services/infection_control_service.py` in `backend-private`
- **Light run and its queue.** Between the full runs (every followed admission, a few times a day), a light run applies the rule only to the admissions queued for it, with the same entry. It is the infection control consumer of the admission queues (see Admission Queues below): prescalc queues an admission followed after its hook (pending or revised) only when an antimicrobial it processed (not suspended) can open a reason, decided in Python by `infection_control_status_service.prescalc_needs_rule` from the record's `indicadores` (one read, only when the prescription has antimicrobials; none otherwise): the drug is not among the running courses (a new drug or a restart; a record prescalc just created has no courses and one it reopened has none, so these are always queued), or its course keeps `evaluatedPosology` (stored by the rule when the evaluation watches posology changes and no posology reason of the drug is open) and none of the drug's items is prescribed as evaluated (`same_posology`, on the drug list fields mapped by `drug_list_posology`). A course kept before `evaluatedPosology` existed doesn't trigger it until the rule runs on it again. A daily prescription repeating a running antimicrobial as evaluated, a CPOE re-run of the day or a prescription without antimicrobials queues nothing. The job entry reads when it was queued before the rule and dequeues after it. A record held by a writer (`skipped` on the lock) stays queued; an admission not followed is dequeued. What only time changes (an evaluation expiring, a course ending, a discharge), a posology change of a course whose evaluation doesn't watch it, a new prescription-day (`fkprescricao_ultima`, whose department, bed and segment the worklist shows) and what doesn't go through prescalc (suspensions) are left to the full run. Tests: `tests/integration/infection_control/test_queue.py`
- **Report summary.** Each run also keeps `ci_atendimento.resumo_acompanhamento` (`services/infection_control/infection_control_summary_service.py`): every antimicrobial course as the timeline groups it (a running one at day precision, `coveredUntil`), and the department of each day. It is written only when it changes, since the job runs several times a day, and the model column is `deferred()`. The infection control report (`reports/InfectionControlReport.py` in `long-running-tasks`) builds its files from it with SQL alone, so the course grouping never leaves this repository: change the summary's contract (`v`, documented in the service's docstring) together with that report. Closed admissions without a summary are filled by `POST /infection-control/backfill-summary`
- Tests: `tests/unit/test_infection_control_status_rule.py` and `tests/integration/infection_control/` (the job entry in `test_job.py`, the summary in `test_summary.py`)

### Admission Queues
- A flow that redoes something per admission when its data changes doesn't go through every admission on a timer: producers queue the admissions that changed and the flow's job (in `backend-private`) runs only on the queued ones. Service `services/admission_queue_service.py`, repository `repository/admission_queue_repository.py`, model `models/admission_queue.py`, table `fila_atendimento` (one per schema)
- One queue per consumer (`tp_fila`, `AdmissionQueueEnum`), one row per consumer and admission (primary key `tp_fila, nratendimento`, the only index the queries need): `dt_fila` is the last time it was queued, `motivos` what queued it (`AdmissionQueueReasonEnum`), `created_at` the first time since it was last dequeued
- **Producers** call `admission_queue_service.notify` in their own transaction, so the queue row commits with the change that queued it. It queues the admission for every consumer in `CONSUMERS` whose feature is on and that wants the producer's change (`AdmissionChange`): `relevant` decides from the change alone, with no query (a change no consumer finds relevant runs none), then `wants` may read the admission, each consumer in a savepoint of its own; it never raises. Prescalc is the only producer so far: it notifies after its hooks, at the end of both entries (`create_agg_prescription_by_prescription` and `create_agg_prescription_by_date`)
- **Consumers** read `get_queued_at` before reading the admission's data and `dequeue` in the same transaction as their work. The row is removed only if `dt_fila` did not change (queued again meanwhile, the change may have come after the reads) and is skipped if a producer holds it. Never dequeue another consumer's rows
- New consumer: a value in `AdmissionQueueEnum`, a `QueueConsumer` in `CONSUMERS`, its entry here dequeuing as above, and the job that lists its queue (`tp_fila`) in `backend-private`. New producer: a reason in `AdmissionQueueReasonEnum` and a `notify` call with its `AdmissionChange` after its writes
- The table needs `DELETE` granted to the api user. Tests: `tests/integration/infection_control/test_queue.py` (the infection control consumer)

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
