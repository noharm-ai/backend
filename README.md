# NoHarm Backend

![Build](https://github.com/noharm-ai/backend/workflows/Build/badge.svg)
[![Issues](https://img.shields.io/github/issues-raw/noharm-ai/backend.svg?maxAge=25000)](https://github.com/noharm-ai/backend/issues)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

REST API for the [NoHarm](https://noharm.ai) clinical decision support platform — a system that helps pharmacists prevent adverse drug events by prioritizing prescriptions, detecting drug interactions, and supporting clinical interventions.

**Current version:** v6.26-beta

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | Flask 3.1.3 |
| ORM | SQLAlchemy 2.0.29 |
| Database | PostgreSQL 16 |
| Cache | Redis |
| Auth | Flask-JWT-Extended |
| Validation | Pydantic 2.9 |
| Deployment | AWS Lambda (Zappa) |
| AI/Agents | Strands Agents, OpenAI / Azure OpenAI, Maritaca |

## Architecture

The application follows a layered architecture with schema-based multi-tenancy (each hospital client gets an isolated PostgreSQL schema):

```
routes/          →  HTTP handling, parameter parsing
services/        →  Business logic, orchestration
repository/      →  Data access, SQL queries
models/          →  SQLAlchemy ORM models + Pydantic request models
```

Key areas covered by the API:

- **Prescription management** — listing, prioritization, clinical checks
- **Drug & substance catalog** — attributes, outlier detection, unit conversion
- **Clinical interventions** — recording, outcomes, workflow
- **Alert system** — drug interactions, allergies, protocols
- **Exam & lab results**
- **Medication conciliation**
- **Clinical notes & summaries** (LLM-powered)
- **Regulatory solicitations**
- **Reporting & analytics**
- **Admin & user management**

## Local Development

### Prerequisites

- Python 3.11+
- PostgreSQL (or Docker for test DB)
- Redis

### Setup

```bash
python3 -m venv env
source env/bin/activate
pip3 install -r requirements.txt
```

### Environment Variables

Copy or set the following variables in your environment (see `config.py` for defaults):

```bash
# Required
ENV=development
SECRET_KEY=your-secret-key
POTGRESQL_CONNECTION_STRING=postgresql://user:password@localhost/noharm
REDIS_HOST=localhost
REDIS_PORT=6379

# Optional
ENCRYPTION_KEY=             # For sensitive data at rest
REPORT_CONNECTION_STRING=   # Separate reporting database
OPEN_AI_API_ENDPOINT=       # Azure OpenAI endpoint
OPEN_AI_API_KEY=
MARITACA_API_KEY=           # Brazilian LLM
ODOO_API_URL=               # ERP integration
```

### Running the Server

```bash
python3 mobile.py
```

The API will be available at `http://127.0.0.1:5000`.

## Testing

Tests require a PostgreSQL database. Use the `make` targets — do **not** run `pytest` directly.

```bash
# First-time setup: starts a Docker container and loads the test schema
make test-setup

# Run all tests
make test

# Run only unit tests (no DB required)
make test-unit

# Run only integration tests
make test-integration

# Run a specific file
make test-file FILE=tests/integration/test_drug.py

# Coverage report (output in htmlcov/)
make test-cov

# Stop / restart the database between sessions (data is preserved)
make db-stop
make db-start

# Full reset: destroy volume and reload from scratch
make db-reset
```

Test database: PostgreSQL 16 via Docker (`docker-compose.test.yml`), schema `demo`, connection `postgresql://postgres@localhost/noharm`.

## Project Structure

```
backend/
├── mobile.py                 # Application entrypoint
├── config.py                 # Configuration (env vars)
├── app/                      # Flask app factory & extensions
├── models/
│   ├── main.py               # Core ORM models
│   ├── prescription.py
│   ├── regulation.py
│   ├── appendix.py
│   ├── enums.py
│   └── requests/             # Pydantic request models
├── repository/               # Database queries
├── services/                 # Business logic
├── routes/                   # Flask blueprints (HTTP layer)
├── decorators/               # @has_permission, @api_endpoint
├── agents/                   # AI agent configurations
├── utils/                    # Date, status, helpers
├── exception/                # Custom exceptions
├── security/                 # Security utilities
├── tests/                    # pytest suite
│   ├── unit/
│   └── integration/
└── scripts/                  # DB setup and maintenance scripts
```

## External Integrations

| Service | Purpose |
|---|---|
| AWS S3 | File storage |
| AWS SQS | Async message processing |
| AWS Lambda | Serverless deployment target |
| AWS CloudWatch | Production logging |
| Odoo | ERP integration |
| OpenAI / Azure OpenAI | Clinical notes summarization, LLM features |
| Maritaca | Brazilian LLM |

## Contributing

Branch strategy:
- `master` — production
- `develop` — integration branch
- Feature branches off `develop`, PR back to `develop`

Code style:
- Follow the existing layered pattern (route → service → repository)
- Use Pydantic models for all request validation
- Add `@has_permission` decorator on service functions that require authorization
- Keep routes thin; business logic belongs in services

## License

[MIT](LICENSE)
