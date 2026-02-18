# NoHarm Backend - Agent Guide

## Overview

NoHarm is a healthcare/pharmacy clinical decision support system that helps prevent adverse drug events. This Flask-based backend provides APIs for prescription management, drug interaction checking, clinical interventions, patient monitoring, and regulatory compliance.

**Tech Stack:** Flask 3.0.3, SQLAlchemy 2.0.29, PostgreSQL, Redis, AWS (S3, SQS, Lambda)

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
- **Connection:** `Config.POTGRESQL_CONNECTION_STRING`
- **ORM:** SQLAlchemy 2.0.29
- **Migrations:** Not currently using Alembic (manual schema management)

### Report Database
- **Bind Name:** `report`
- **Connection:** `Config.REPORT_CONNECTION_STRING`
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
- `POTGRESQL_CONNECTION_STRING`: Main database URL
- `REDIS_HOST`, `REDIS_PORT`: Redis connection

**Optional but Important:**
- `ENCRYPTION_KEY`: For sensitive data encryption
- `API_KEY`: Internal API authentication
- `SERVICE_INFERENCE`: ML service endpoint
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
- **Run:** `pytest`

### Test Database
Override in TestConfig (app/flask_config.py)

### Test Ordering
Use `@pytest.mark.order(n)` for test execution order

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

### Git Workflow
- Main branch: `master`
- Development branch: `develop`
- Feature branches off `develop`
- PR to `develop`, then merge to `master`

## Useful Commands

```bash
# Run development server
python3 mobile.py

# Run tests
pytest

# Run tests with coverage
pytest --cov=. --cov-report=html

# Check code style
pylint services/
```

## AI/ML Features

### LLM Integration
- Services: `llm_service.py`, `agents/`
- Providers: OpenAI/Azure OpenAI, Maritaca
- Use cases: Clinical notes summarization, drug name normalization

### Inference Service
- External ML service for predictions
- Configuration: `SERVICE_INFERENCE` environment variable
- Used for conversion predictions, risk scoring

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
- **Python Version:** 3.11+
- **Documentation:** This file + code comments
